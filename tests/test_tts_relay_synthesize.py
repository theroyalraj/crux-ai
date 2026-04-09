from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from server.config import get_settings
from server.routes.speak import SpeakBody, tts_synthesize
from server.tts.service import reset_tts_service_for_tests


@pytest.mark.asyncio
async def test_tts_synthesize_503_when_disabled() -> None:
    mock_s = MagicMock()
    mock_s.CRUX_TTS_SYNTHESIZE_ENABLED = False
    with patch("server.routes.speak.get_settings", return_value=mock_s):
        with pytest.raises(HTTPException) as exc:
            await tts_synthesize(SpeakBody(text="hello there"))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_tts_synthesize_returns_mp3_when_enabled() -> None:
    mock_s = MagicMock()
    mock_s.CRUX_TTS_SYNTHESIZE_ENABLED = True
    mock_svc = MagicMock()
    mock_svc.synthesize_mp3 = AsyncMock(return_value=(b"\xff\xf3\xab", "eleven"))
    with (
        patch("server.routes.speak.get_settings", return_value=mock_s),
        patch("server.routes.speak.get_tts_service", return_value=mock_svc),
    ):
        resp = await tts_synthesize(SpeakBody(text="hello"))
    assert resp.media_type == "audio/mpeg"
    assert resp.body == b"\xff\xf3\xab"
    assert resp.headers["X-Crux-Tts-Provider"] == "eleven"


@pytest.mark.asyncio
async def test_tts_synthesize_502_when_no_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRUX_TTS_SYNTHESIZE_ENABLED", "true")
    get_settings.cache_clear()
    reset_tts_service_for_tests()
    mock_s = get_settings()
    assert mock_s.CRUX_TTS_SYNTHESIZE_ENABLED is True
    mock_svc = MagicMock()
    mock_svc.synthesize_mp3 = AsyncMock(return_value=None)
    with patch("server.routes.speak.get_tts_service", return_value=mock_svc):
        with patch("server.routes.speak.get_settings", return_value=mock_s):
            with pytest.raises(HTTPException) as exc:
                await tts_synthesize(SpeakBody(text="hello"))
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_relay_provider_posts_synthesize_and_plays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRUX_TTS_RELAY_BASE_URL", "https://upstream.example")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "server.tts.providers.relay_provider.engine.mp3_playback_available",
        lambda: True,
    )
    played: list[bytes] = []

    async def fake_play(data: bytes, generation_ok):  # noqa: ANN001
        played.append(data)
        return 0.0

    monkeypatch.setattr(
        "server.tts.providers.relay_provider.engine.playback_mp3_bytes",
        fake_play,
    )
    from server.tts.providers.relay_provider import RelayTtsProvider

    posted_urls: list[str] = []

    class FakeResp:
        content = b"relay-mp3"

        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *a):  # noqa: ANN002
            return None

        async def post(self, url: str, **kwargs):  # noqa: ANN003
            posted_urls.append(url)
            return FakeResp()

    monkeypatch.setattr(
        "server.tts.providers.relay_provider.httpx.AsyncClient",
        lambda **kw: FakeClient(),
    )
    prov = RelayTtsProvider()
    assert prov.is_available() is True

    from server.tts.contract import TtsPlaybackRequest

    req = TtsPlaybackRequest(
        text="hi",
        edge_voice="en-US-JennyNeural",
        edge_rate="+0%",
        edge_pitch="+0Hz",
        say_voice="Samantha",
        say_wpm=200,
        stream=False,
        eleven_voice_id="x",
        eleven_model_id="y",
        eleven_output_format="mp3_44100_128",
        persona="forge",
    )
    ok = True

    async def gen_ok():
        return ok

    await prov.speak(req, gen_ok)
    assert posted_urls == ["https://upstream.example/tts/synthesize"]
    assert played == [b"relay-mp3"]
