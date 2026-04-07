from __future__ import annotations

from collections.abc import Awaitable, Callable

from server.tts import engine
from server.tts.contract import TtsPlaybackRequest


class MacSayProvider:
    id = "say"

    def is_available(self) -> bool:
        return engine.speak_say.is_available()

    async def speak(
        self,
        request: TtsPlaybackRequest,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        return await engine.speak_say(
            request.text,
            request.say_voice,
            request.say_wpm,
            generation_ok,
        )
