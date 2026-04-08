from __future__ import annotations

import os
import tempfile
from collections.abc import Awaitable, Callable

import structlog

from server.tts import engine
from server.tts.contract import TtsPlaybackRequest
from server.tts.voices import resolve_edge_voice

log = structlog.get_logger(__name__)


class EdgeTtsProvider:
    id = "edge"

    def is_available(self) -> bool:
        return engine.speak_edge.is_available()

    async def speak(
        self,
        request: TtsPlaybackRequest,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        return await engine.speak_edge(
            request.text,
            voice=request.edge_voice,
            rate=request.edge_rate,
            pitch=request.edge_pitch,
            stream=request.stream,
            generation_ok=generation_ok,
        )

    async def synthesize_mp3(self, request: TtsPlaybackRequest) -> bytes | None:
        import edge_tts

        v = resolve_edge_voice(request.edge_voice)
        comm = edge_tts.Communicate(
            request.text,
            v,
            rate=request.edge_rate,
            pitch=request.edge_pitch,
        )
        path: str | None = None
        data = b""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", prefix="crux-tts-", delete=False) as f:
                path = f.name
            await comm.save(path)
            with open(path, "rb") as f:
                data = f.read()
        except Exception as e:
            log.warning("edge_tts_synthesize_failed", err=str(e))
            raise
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return data if data.strip() else None
