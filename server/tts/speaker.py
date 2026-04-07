from __future__ import annotations

import structlog

from server.config import get_settings
from server.db.redis_client import get_redis
from server.tts.lock import (
    acquire_speaker_lock,
    current_generation,
    incr_generation,
    release_speaker_lock,
)
from server.tts.service import get_tts_service

log = structlog.get_logger(__name__)


async def speak_text(
    text: str,
    *,
    persona: str | None = None,
    priority: bool = False,
) -> float:
    settings = get_settings()
    if not settings.CRUX_TTS_ENABLED:
        return 0.0

    redis_client = get_redis()
    # Priority bumps generation so in-flight speech stops (preempt). Non-priority reuses the
    # current counter so many /speak-async calls queue without invalidating each other's gen_ok.
    if priority:
        my_gen = await incr_generation(redis_client)
    else:
        my_gen = await current_generation(redis_client)

    async def gen_ok() -> bool:
        cur = await current_generation(redis_client)
        return cur == my_gen

    if not await gen_ok():
        return 0.0

    token, used_redis = await acquire_speaker_lock(
        redis_client,
        priority=priority,
        ttl_sec=settings.CRUX_TTS_LOCK_TTL_SEC,
    )
    if token is None:
        log.warning("speaker_lock_unavailable")
        return 0.0

    if not await gen_ok():
        await release_speaker_lock(redis_client, token, used_redis)
        return 0.0

    try:
        svc = get_tts_service()
        await svc.speak(
            text,
            persona=persona,
            stream=settings.CRUX_TTS_STREAM,
            generation_ok=gen_ok,
        )
    finally:
        await release_speaker_lock(redis_client, token, used_redis)
    return 0.0
