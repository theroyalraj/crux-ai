from __future__ import annotations

import redis.asyncio as redis
from redis.asyncio import Redis

from server.config import CruxSettings, get_settings

_client: Redis | None = None


async def init_redis(settings: CruxSettings | None = None) -> Redis | None:
    global _client
    settings = settings or get_settings()
    try:
        _client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await _client.ping()
        return _client
    except Exception:
        _client = None
        return None


def get_redis() -> Redis | None:
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
