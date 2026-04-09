from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from server.config import get_settings
from server.tts import engine
from server.tts.contract import TtsPlaybackRequest

log = structlog.get_logger(__name__)


def _relay_headers() -> dict[str, str]:
    raw = (get_settings().CRUX_TTS_RELAY_EXTRA_HEADERS_JSON or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("tts_relay_extra_headers_invalid_json")
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = str(v)
    return out


class RelayTtsProvider:
    id = "relay"

    def is_available(self) -> bool:
        s = get_settings()
        if not (s.CRUX_TTS_RELAY_BASE_URL or "").strip():
            return False
        return engine.mp3_playback_available()

    async def speak(
        self,
        request: TtsPlaybackRequest,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        s = get_settings()
        base = (s.CRUX_TTS_RELAY_BASE_URL or "").strip().rstrip("/")
        if not base:
            return 0.0
        url = f"{base}/tts/synthesize"
        persona = request.persona
        payload: dict[str, Any] = {"text": request.text, "priority": False}
        if persona:
            payload["persona"] = persona
        headers = {"Content-Type": "application/json", **_relay_headers()}
        try:
            async with httpx.AsyncClient(
                timeout=s.CRUX_TTS_RELAY_TIMEOUT_SEC,
            ) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                audio = r.content
        except httpx.HTTPError as e:
            log.warning("tts_relay_http_failed", err=str(e))
            raise
        if not audio.strip():
            raise RuntimeError("tts_relay_empty_audio")
        return await engine.playback_mp3_bytes(audio, generation_ok)
