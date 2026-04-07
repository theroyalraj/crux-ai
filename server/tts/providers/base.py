from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from server.tts.contract import TtsPlaybackRequest


@runtime_checkable
class TtsProvider(Protocol):
    """Pluggable TTS backend (macOS say, Edge neural, future Hindi/local engines)."""

    @property
    def id(self) -> str: ...

    def is_available(self) -> bool: ...

    async def speak(
        self,
        request: TtsPlaybackRequest,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float: ...
