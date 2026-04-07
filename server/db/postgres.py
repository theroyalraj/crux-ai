from __future__ import annotations

import asyncpg
from pgvector.asyncpg import register_vector

from server.config import CruxSettings, get_settings

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def init_postgres(settings: CruxSettings | None = None) -> asyncpg.Pool | None:
    global _pool
    settings = settings or get_settings()
    try:
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=5,
            init=_init_conn,
        )
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return _pool
    except Exception:
        _pool = None
        return None


def get_pool() -> asyncpg.Pool | None:
    return _pool


async def close_postgres() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
