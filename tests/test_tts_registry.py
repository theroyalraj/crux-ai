from __future__ import annotations

import sys
from typing import Any

import pytest

from server.config import get_settings
from server.tts.config_loader import deep_merge, effective_provider_chain, load_merged_registry


def _flatten_say_pool(pool: dict[str, Any]) -> set[str]:
    return {v for voices in pool["say"].values() for v in voices}


def _flatten_edge_pool(pool: dict[str, Any]) -> set[str]:
    return {v for voices in pool["edge"].values() for v in voices}


def _flatten_eleven_pool(pool: dict[str, Any]) -> set[str]:
    el = pool.get("eleven") or {}
    if not isinstance(el, dict):
        return set()
    return {v for voices in el.values() for v in voices}


def test_bundled_registry_has_locales_and_hi_in() -> None:
    r = load_merged_registry(get_settings())
    assert r["version"] == 2
    assert "en-US" in r["locales"]
    assert "hi-IN" in r["locales"]
    assert r["locales"]["hi-IN"]["chain"] == ["eleven", "edge"]
    assert r["personas"]["priya"]["locale"] == "hi-IN"
    assert r["personas"]["siri"]["locale"] == "en-US"
    assert r["personas"]["siri"]["overrides"]["say"]["voice"] == "Aman"


def test_voice_pool_covers_all_persona_and_locale_voices() -> None:
    r = load_merged_registry(get_settings())
    pool = r["voice_pool"]
    say_ok = _flatten_say_pool(pool)
    edge_ok = _flatten_edge_pool(pool)
    eleven_ok = _flatten_eleven_pool(pool)

    for loc, loc_data in r["locales"].items():
        voices = loc_data.get("voices", {})
        if "say" in voices:
            assert voices["say"]["voice"] in say_ok
        if "edge" in voices:
            assert voices["edge"]["voice"] in edge_ok
        if "eleven" in voices:
            assert voices["eleven"]["voice_id"] in eleven_ok
            assert loc in (pool.get("eleven") or {})

    for _pk, pdata in r["personas"].items():
        ovr = pdata.get("overrides", {})
        if "say" in ovr:
            assert ovr["say"]["voice"] in say_ok
        if "edge" in ovr:
            assert ovr["edge"]["voice"] in edge_ok
        if "eleven" in ovr:
            assert ovr["eleven"]["voice_id"] in eleven_ok


def test_deep_merge_overrides_locale() -> None:
    base = {"locales": {"en-US": {"voices": {"say": {"voice": "A"}}}}}
    over = {"locales": {"en-US": {"voices": {"say": {"wpm": 222}}}}}
    m = deep_merge(base, over)
    assert m["locales"]["en-US"]["voices"]["say"]["voice"] == "A"
    assert m["locales"]["en-US"]["voices"]["say"]["wpm"] == 222


def test_effective_chain_respects_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    r = load_merged_registry(get_settings())
    monkeypatch.setattr(sys, "platform", "linux")
    get_settings.cache_clear()
    s = get_settings()
    ch = effective_provider_chain(r, ["say", "edge"], s)
    assert ch == ["edge"]


def test_effective_chain_darwin_prefers_say_first(monkeypatch: pytest.MonkeyPatch) -> None:
    r = load_merged_registry(get_settings())
    monkeypatch.setattr(sys, "platform", "darwin")
    get_settings.cache_clear()
    s = get_settings()
    ch = effective_provider_chain(r, ["say", "edge"], s)
    assert ch[0] == "say"


def test_forced_edge_skips_say(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUX_TTS_PROVIDER", "edge")
    get_settings.cache_clear()
    r = load_merged_registry(get_settings())
    monkeypatch.setattr(sys, "platform", "darwin")
    ch = effective_provider_chain(r, ["say", "edge"], get_settings())
    assert ch == ["edge"]


def test_effective_chain_strips_eleven_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRUX_ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("CRUX_ELEVENLABS_API_KEY", "")
    get_settings.cache_clear()
    r = load_merged_registry(get_settings())
    monkeypatch.setattr(sys, "platform", "darwin")
    ch = effective_provider_chain(r, ["eleven", "say", "edge"], get_settings())
    assert ch == ["say", "edge"]


def test_effective_chain_keeps_eleven_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUX_ELEVENLABS_API_KEY", "x")
    get_settings.cache_clear()
    r = load_merged_registry(get_settings())
    monkeypatch.setattr(sys, "platform", "darwin")
    ch = effective_provider_chain(r, ["eleven", "say", "edge"], get_settings())
    assert ch == ["eleven", "say", "edge"]
