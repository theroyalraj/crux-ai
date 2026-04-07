from __future__ import annotations

from server.tts.lock import KEY_GEN, KEY_LOCK, RELEASE_LUA


def test_lock_constants() -> None:
    assert KEY_LOCK.startswith("crux:")
    assert KEY_GEN.startswith("crux:")
    assert "redis.call" in RELEASE_LUA
