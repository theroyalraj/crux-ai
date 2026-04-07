from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import structlog

from server.config import get_settings
from server.daemons.base import BaseDaemon
from server.git.ops import default_branch, is_dirty, run_git
from server.llm.router import chat

log = structlog.get_logger(__name__)

_hourly_box: HourlyDecisionBox | None = None


class HourlyDecisionBox:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._decision: str | None = None

    def reset(self) -> None:
        self._event.clear()
        self._decision = None

    def submit(self, decision: str) -> None:
        d = (decision or "no").strip().lower()
        if d not in ("yes", "no"):
            d = "no"
        self._decision = d
        self._event.set()

    async def wait(self, timeout: float) -> str:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return self._decision or "no"
        except TimeoutError:
            return "timeout"


def get_hourly_decision_box() -> HourlyDecisionBox | None:
    return _hourly_box


async def _fetch_rebase() -> tuple[bool, str]:
    await run_git("fetch", "origin")
    branch = await default_branch()
    code, out, err = await run_git("rebase", f"origin/{branch}", check=False)
    if code != 0:
        await run_git("rebase", "--abort", check=False)
        return False, (err or out or "rebase failed").strip()
    return True, ""


class CommitterDaemon(BaseDaemon):
    def __init__(self) -> None:
        super().__init__("committer")

    async def start(self) -> None:
        global _hourly_box
        _hourly_box = HourlyDecisionBox()
        await super().start()

    async def stop(self) -> None:
        global _hourly_box
        await super().stop()
        _hourly_box = None

    async def run_loop(self) -> None:
        settings = get_settings()
        interval_sec = max(1, settings.CRUX_GIT_COMMIT_INTERVAL_MIN) * 60
        var_dir = Path(__file__).resolve().parent.parent.parent / "var"
        var_dir.mkdir(parents=True, exist_ok=True)
        fail_log = var_dir / "hourly-rebase-failure.log"

        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval_sec)
                break
            except TimeoutError:
                pass
            if self._stop.is_set():
                break

            try:
                if not await is_dirty():
                    await self.speak("Working tree clean.", persona="chronicle", priority=False)
                    continue

                _, stat, _ = await run_git("diff", "--stat", check=False)
                summary_prompt = (
                    f"Summarize this git change stat in one short plain sentence.\n\n{stat[:8000]}"
                )
                try:
                    narr = await chat(
                        summary_prompt,
                        system="Plain English only, no markdown.",
                        source="hourly",
                    )
                    line = str(narr.get("response", "You have uncommitted changes."))[:500]
                except Exception:
                    line = "You have uncommitted changes."

                box = _hourly_box
                if box is None:
                    continue
                box.reset()
                prompt = (
                    f"{line} Should I commit and push? Say yes or no in the app within ten minutes."
                )
                await self.speak(prompt, persona="chronicle", priority=True)

                decision = await box.wait(float(settings.CRUX_HOURLY_CONFIRM_TIMEOUT_SEC))

                if decision == "timeout":
                    await self.speak(
                        "No reply. Skipping commit for now.",
                        persona="chronicle",
                        priority=False,
                    )
                    if settings.CRUX_HOURLY_REBASE_ON_TIMEOUT:
                        ok, err = await _fetch_rebase()
                        if not ok:
                            ts = datetime.now(UTC).isoformat()
                            fail_log.write_text(f"{ts}\n{err}\n", encoding="utf-8")
                            await self.speak(
                                "Rebase failed. Please fix conflicts.",
                                persona="chronicle",
                                priority=True,
                            )
                    continue

                ok, err = await _fetch_rebase()
                if not ok:
                    ts = datetime.now(UTC).isoformat()
                    fail_log.write_text(f"{ts}\n{err}\n", encoding="utf-8")
                    await self.speak(
                        "Rebase failed. Please fix conflicts manually.",
                        persona="chronicle",
                        priority=True,
                    )
                    continue

                if decision == "no":
                    await self.speak(
                        "Okay, no commit. Your branch is rebased.",
                        persona="chronicle",
                        priority=False,
                    )
                    continue

                if decision == "yes" and settings.CRUX_GIT_AUTO_COMMIT:
                    _, diff, _ = await run_git("diff", check=False)
                    cm = await chat(
                        "Write a conventional commit subject and short body for:\n\n"
                        f"{diff[:20000]}",
                        system="Output only the commit message, no fences.",
                        source="hourly_commit",
                    )
                    msg = str(cm.get("response", "chore: checkpoint")).strip()[:4000]
                    await run_git("add", "-A")
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=".gitmsg.txt",
                        delete=False,
                        encoding="utf-8",
                    ) as f:
                        f.write(msg)
                        gpath = f.name
                    try:
                        await run_git("commit", "-F", gpath, check=False)
                    finally:
                        try:
                            os.unlink(gpath)
                        except OSError:
                            pass

                if decision == "yes":
                    try:
                        await run_git("push", "-u", "origin", "HEAD", check=False)
                    except Exception:
                        log.warning("push_failed")

                await self.speak("Done with checkpoint flow.", persona="chronicle", priority=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("committer_cycle_failed")
