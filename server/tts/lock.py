from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

KEY_LOCK = "crux:speaker:lock"
KEY_GEN = "crux:speaker:generation"

RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""

FILE_LOCK = Path(tempfile.gettempdir()) / "crux-speaker-active"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def incr_generation(redis_client) -> int:
    if redis_client is None:
        return 0
    try:
        v = await redis_client.incr(KEY_GEN)
        return int(v)
    except Exception as e:
        log.warning("generation_incr_failed", err=str(e))
        return 0


async def current_generation(redis_client) -> int:
    if redis_client is None:
        return 0
    try:
        raw = await redis_client.get(KEY_GEN)
        return int(raw) if raw is not None else 0
    except Exception:
        return 0


async def acquire_speaker_lock(
    redis_client,
    *,
    priority: bool,
    ttl_sec: int,
    wait_timeout_sec: float = 120.0,
) -> tuple[str | None, bool]:
    """
    Returns (token, used_redis). token None means failed.
    If Redis unavailable, uses file+PID fallback when possible.
    """
    token = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_timeout_sec

    if redis_client is not None:
        while loop.time() < deadline:
            try:
                if priority:
                    await redis_client.delete(KEY_LOCK)
                ok = await redis_client.set(KEY_LOCK, token, nx=True, ex=ttl_sec)
                if ok:
                    return token, True
            except Exception as e:
                log.warning("redis_lock_acquire_error", err=str(e))
                break
            await asyncio.sleep(0.08)

    # fail-open file lock
    try:
        while loop.time() < deadline:
            if FILE_LOCK.exists():
                try:
                    old = int(FILE_LOCK.read_text().strip())
                    if _pid_alive(old):
                        if priority:
                            FILE_LOCK.unlink(missing_ok=True)
                        else:
                            await asyncio.sleep(0.08)
                            continue
                except (ValueError, OSError):
                    FILE_LOCK.unlink(missing_ok=True)
            FILE_LOCK.write_text(str(os.getpid()))
            return token, False
    except OSError as e:
        log.warning("file_lock_failed", err=str(e))
    return None, False


async def release_speaker_lock(redis_client, token: str | None, used_redis: bool) -> None:
    if not token:
        return
    if used_redis and redis_client is not None:
        try:
            await redis_client.eval(RELEASE_LUA, 1, KEY_LOCK, token)
        except Exception as e:
            log.warning("redis_lock_release_error", err=str(e))
    try:
        if FILE_LOCK.exists():
            mine = FILE_LOCK.read_text().strip() == str(os.getpid())
            if mine:
                FILE_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


async def force_clear_all_locks(redis_client) -> None:
    if redis_client is not None:
        try:
            await redis_client.delete(KEY_LOCK, KEY_GEN, "crux:speaker:thinking")
        except Exception as e:
            log.warning("redis_clear_locks", err=str(e))
    FILE_LOCK.unlink(missing_ok=True)
