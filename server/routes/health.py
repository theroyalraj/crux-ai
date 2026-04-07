from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    redis_ok = False
    postgres_ok = False
    try:
        from server.db.redis_client import get_redis

        r = get_redis()
        if r is not None:
            await r.ping()
            redis_ok = True
    except Exception:
        redis_ok = False

    try:
        from server.db.postgres import get_pool

        pool = get_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            postgres_ok = True
    except Exception:
        postgres_ok = False

    dm: dict[str, bool] = {}
    daemons = getattr(request.app.state, "daemons", None) or {}
    for name, d in daemons.items():
        try:
            dm[name] = d.health()
        except Exception:
            dm[name] = False

    return {
        "status": "ok",
        "redis": redis_ok,
        "postgres": postgres_ok,
        "daemons": dm,
    }
