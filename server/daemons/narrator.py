from __future__ import annotations

import asyncio

import structlog

from server.daemons.base import BaseDaemon

log = structlog.get_logger(__name__)


class NarratorDaemon(BaseDaemon):
    def __init__(self) -> None:
        super().__init__("narrator")

    async def run_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3600)
                break
            except TimeoutError:
                log.debug("narrator_tick")
