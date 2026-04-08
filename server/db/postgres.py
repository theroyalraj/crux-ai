from __future__ import annotations

from pathlib import Path

import asyncpg
import structlog
from pgvector.asyncpg import register_vector

from server.config import CruxSettings, get_settings

_pool: asyncpg.Pool | None = None
log = structlog.get_logger(__name__)


async def run_migrations(pool: asyncpg.Pool) -> None:
    migration_path = Path(__file__).parent / "migrations" / "001_action_items.sql"
    if not migration_path.is_file():
        return
    raw = migration_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in raw.split(";") if s.strip()]
    async with pool.acquire() as conn:
        for stmt in statements:
            await conn.execute(stmt + ";")


async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def init_postgres(settings: CruxSettings | None = None) -> asyncpg.Pool | None:
    global _pool
    settings = settings or get_settings()
    dsn = settings.postgres_dsn()
    try:
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=5,
            init=_init_conn,
        )
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        await run_migrations(_pool)
        log.info("postgres_pool_ready", dsn_host=_dsn_log_fragment(dsn))
        return _pool
    except Exception as exc:
        log.exception("postgres_init_failed", error=str(exc), dsn_host=_dsn_log_fragment(dsn))
        _pool = None
        return None


def _dsn_log_fragment(dsn: str) -> str:
    """Log host/db without password (asyncpg URL is postgresql://user:pass@host:port/db)."""
    try:
        from urllib.parse import urlparse

        u = urlparse(dsn)
        return f"{u.hostname}:{u.port or 5432}/{u.path.lstrip('/') or '?'}"
    except Exception:
        return "?"


def get_pool() -> asyncpg.Pool | None:
    return _pool


async def close_postgres() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
