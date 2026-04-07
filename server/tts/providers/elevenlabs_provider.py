from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import structlog

from server.config import CruxSettings, get_settings
from server.tts import engine
from server.tts.contract import TtsPlaybackRequest
from server.tts.eleven_cache import eleven_cache_get, eleven_cache_key, eleven_cache_set

log = structlog.get_logger(__name__)


def _eleven_httpx_verify(s: CruxSettings) -> bool | str:
    if not s.CRUX_ELEVENLABS_VERIFY_TLS:
        return False
    ca = (s.CRUX_ELEVENLABS_SSL_CA_BUNDLE or "").strip()
    return ca if ca else True


class ElevenLabsTtsProvider:
    id = "eleven"

    def is_available(self) -> bool:
        s = get_settings()
        if not s.CRUX_ELEVENLABS_ENABLED:
            return False
        if not (s.CRUX_ELEVENLABS_API_KEY or "").strip():
            return False
        return engine.edge_playback_available()

    async def speak(
        self,
        request: TtsPlaybackRequest,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        s = get_settings()
        if not await engine.generation_allowed(generation_ok):
            return 0.0

        voice_id = request.eleven_voice_id
        model_id = request.eleven_model_id
        output_format = request.eleven_output_format
        cache_payload = {
            "text": request.text,
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
        }
        ck = eleven_cache_key(cache_payload)
        cached = await eleven_cache_get(ck)
        if cached:
            log.info("eleven_tts_cache_hit", voice_id=voice_id)
            return await engine.playback_mp3_bytes(cached, generation_ok)

        base = (s.CRUX_ELEVENLABS_BASE_URL or "https://api.elevenlabs.io").rstrip("/")
        url = f"{base}/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": s.CRUX_ELEVENLABS_API_KEY.strip(),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = {"text": request.text, "model_id": model_id}
        params = {"output_format": output_format}

        chunks: list[bytes] = []
        verify = _eleven_httpx_verify(s)
        if verify is False:
            log.warning("eleven_tts_tls_verify_disabled")
        try:
            async with httpx.AsyncClient(
                timeout=s.CRUX_ELEVENLABS_TIMEOUT_SEC,
                verify=verify,
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=body,
                    params=params,
                ) as resp:
                    if resp.status_code in (401, 403):
                        log.warning(
                            "eleven_tts_auth_failed",
                            status=resp.status_code,
                            detail="fallback_to_next_provider",
                        )
                        resp.raise_for_status()
                    resp.raise_for_status()
                    async for part in resp.aiter_bytes():
                        if not await engine.generation_allowed(generation_ok):
                            raise RuntimeError("eleven_tts_generation_preempted")
                        if part:
                            chunks.append(part)
        except httpx.HTTPStatusError as e:
            log.warning(
                "eleven_tts_http_error",
                status=e.response.status_code if e.response else None,
                err=str(e),
            )
            raise
        except Exception as e:
            log.warning("eleven_tts_request_failed", err=str(e))
            raise

        audio = b"".join(chunks)
        if not audio.strip():
            raise RuntimeError("eleven_tts_empty_audio")

        await eleven_cache_set(ck, audio, s.CRUX_TTS_ELEVEN_CACHE_TTL_SEC)
        return await engine.playback_mp3_bytes(audio, generation_ok)
