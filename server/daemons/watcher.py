from __future__ import annotations

import asyncio
import time

import structlog
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from server.config import get_settings
from server.daemons.base import BaseDaemon
from server.git.ops import repo_path

log = structlog.get_logger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_event: asyncio.AbstractEventLoop, debounce: float, speak_coro) -> None:
        self._loop = on_event
        self._debounce = debounce
        self._speak = speak_coro
        self._last = 0.0

    def on_any_event(self, event) -> None:
        if event.is_directory:
            return
        path = getattr(event, "src_path", "") or ""
        if ".git" in path or "__pycache__" in path or path.endswith(".pyc"):
            return
        now = time.monotonic()
        if now - self._last < self._debounce:
            return
        self._last = now

        async def _do():
            s = get_settings()
            if s.CRUX_WATCHER_SPEAK_ENABLED:
                await self._speak("Workspace file changed.", persona="echo", priority=False)
            else:
                log.debug("watcher_file_event", path=path)

        asyncio.run_coroutine_threadsafe(_do(), self._loop)


class WatcherDaemon(BaseDaemon):
    def __init__(self) -> None:
        super().__init__("watcher")
        self._observer: Observer | None = None

    async def run_loop(self) -> None:
        settings = get_settings()
        root = repo_path()
        loop = asyncio.get_running_loop()

        async def speak_fn(text: str, *, persona: str | None = None, priority: bool = False):
            await self.speak(text, persona=persona, priority=priority)

        handler = _Handler(loop, settings.CRUX_WATCHER_DEBOUNCE_SEC, speak_fn)
        self._observer = Observer()
        self._observer.schedule(handler, str(root), recursive=True)
        self._observer.start()
        try:
            await self._stop.wait()
        finally:
            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=5)
                self._observer = None
