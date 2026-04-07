from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import structlog

from server.db.redis_client import get_redis

log = structlog.get_logger(__name__)

# Namespace for SCAN/clear on boot. Values are base64(mp3); client uses decode_responses.
ELEVEN_TTS_CACHE_PREFIX = "crux:tts:eleven:v1:"


def eleven_cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    return f"{ELEVEN_TTS_CACHE_PREFIX}{h}"


async def eleven_cache_get(key: str) -> bytes | None:
    r = get_redis()
    if r is None:
        return None
    try:
        b64 = await r.get(key)
        if not b64:
            return None
        return base64.b64decode(b64.encode("ascii"))
    except Exception as e:
        log.warning("eleven_tts_cache_get_failed", err=str(e))
        return None


async def eleven_cache_set(key: str, audio: bytes, ttl_sec: int) -> None:
    r = get_redis()
    if r is None or ttl_sec <= 0:
        return
    try:
        b64 = base64.b64encode(audio).decode("ascii")
        await r.set(key, b64, ex=ttl_sec)
    except Exception as e:
        log.warning("eleven_tts_cache_set_failed", err=str(e))


async def clear_eleven_tts_cache() -> int:
    """Delete all ElevenLabs TTS audio keys. Called at server startup."""
    r = get_redis()
    if r is None:
        return 0
    n = 0
    try:
        async for key in r.scan_iter(match=f"{ELEVEN_TTS_CACHE_PREFIX}*"):
            await r.delete(key)
            n += 1
    except Exception as e:
        log.warning("eleven_tts_cache_clear_failed", err=str(e))
    if n:
        log.info("eleven_tts_cache_cleared_on_startup", keys=n)
    return n
