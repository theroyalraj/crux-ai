from __future__ import annotations

from collections.abc import Awaitable, Callable

from server.tts import engine
from server.tts.contract import TtsPlaybackRequest


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
