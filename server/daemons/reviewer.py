from __future__ import annotations

import asyncio

import structlog

from server.config import get_settings
from server.daemons.base import BaseDaemon
from server.git.ops import is_dirty, run_git
from server.git.review import review_diff

log = structlog.get_logger(__name__)


class ReviewerDaemon(BaseDaemon):
    def __init__(self) -> None:
        super().__init__("reviewer")

    async def run_loop(self) -> None:
        settings = get_settings()
        interval = max(5, settings.CRUX_REVIEWER_INTERVAL_MIN) * 60
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            try:
                if not await is_dirty():
                    continue
                _, diff, _ = await run_git("diff", check=False)
                if not diff.strip():
                    _, diff, _ = await run_git("diff", "HEAD~1", check=False)
                if not diff.strip():
                    continue
                result = await review_diff(diff)
                summary = str(result.get("summary", ""))[:400]
                if summary:
                    await self.speak(f"Review note. {summary}", persona="sentinel", priority=False)
            except Exception:
                log.exception("reviewer_cycle_failed")
