from __future__ import annotations

import pytest

from server.config import get_settings
from server.tts.service import reset_tts_service_for_tests


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate from developer .env (e.g. CRUX_TTS_PROVIDER) so registry tests stay deterministic.
    monkeypatch.setenv("CRUX_TTS_PROVIDER", "")
    monkeypatch.setenv("CRUX_TTS_RELAY_BASE_URL", "")
    monkeypatch.setenv("CRUX_TTS_SYNTHESIZE_ENABLED", "false")
    reset_tts_service_for_tests()
    get_settings.cache_clear()
    yield
    reset_tts_service_for_tests()
    get_settings.cache_clear()
