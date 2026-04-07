from __future__ import annotations

import asyncio
import traceback

import structlog

from server.tts.speaker import speak_text

log = structlog.get_logger(__name__)


class BaseDaemon:
    def __init__(self, name: str) -> None:
        self.name = name
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._safe_run(), name=f"crux-daemon-{self.name}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def health(self) -> bool:
        return self._task is not None and not self._task.done()

    async def speak(self, text: str, *, persona: str | None = None, priority: bool = False) -> None:
        await speak_text(text, persona=persona, priority=priority)

    async def _safe_run(self) -> None:
        try:
            await self.run_loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daemon_crashed", name=self.name, tb=traceback.format_exc())

    async def run_loop(self) -> None:
        raise NotImplementedError
