from __future__ import annotations

import asyncio

import structlog

from server.config import get_settings
from server.daemons.base import BaseDaemon

log = structlog.get_logger(__name__)


class AmbientDaemon(BaseDaemon):
    def __init__(self) -> None:
        super().__init__("ambient")

    async def run_loop(self) -> None:
        settings = get_settings()
        interval = max(60, settings.CRUX_AMBIENT_INTERVAL_SEC)
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                await self.speak(
                    "Time for a short break and some water.",
                    persona="maestro",
                    priority=False,
                )
            except Exception:
                log.exception("ambient_speak_failed")
