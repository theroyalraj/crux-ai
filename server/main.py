from __future__ import annotations

import asyncio
import glob
import logging
import os
import sys
import tempfile
import warnings

# OpenClaw / Python 3.13+ Windows: Proactor + some SSL/WebSocket stacks are flaky;
# Selector policy matches skill-gateway/scripts/friday-speak.py.
if sys.platform == "win32":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from server.config import get_settings
from server.daemons.ambient import AmbientDaemon
from server.daemons.committer import CommitterDaemon
from server.daemons.narrator import NarratorDaemon
from server.daemons.reviewer import ReviewerDaemon
from server.daemons.watcher import WatcherDaemon
from server.db import close_postgres, close_redis, init_postgres, init_redis
from server.db.redis_client import get_redis
from server.routes import git_routes, health, internal, llm, speak
from server.tts import force_clear_all_locks, kill_all_audio
from server.tts.eleven_cache import clear_eleven_tts_cache

log = structlog.get_logger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def cleanup_temp_files() -> None:
    for p in glob.glob(os.path.join(tempfile.gettempdir(), "crux-tts*.mp3")):
        try:
            os.unlink(p)
        except OSError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.CRUX_LOG_LEVEL)

    await init_redis(settings)
    await clear_eleven_tts_cache()
    await init_postgres(settings)

    daemons_list = []
    if settings.CRUX_ENABLED:
        if settings.CRUX_NARRATOR_ENABLED:
            daemons_list.append(NarratorDaemon())
        if settings.CRUX_REVIEWER_ENABLED:
            daemons_list.append(ReviewerDaemon())
        if settings.CRUX_COMMITTER_ENABLED:
            daemons_list.append(CommitterDaemon())
        if settings.CRUX_AMBIENT_ENABLED:
            daemons_list.append(AmbientDaemon())
        if settings.CRUX_WATCHER_ENABLED:
            daemons_list.append(WatcherDaemon())

        for d in daemons_list:
            await d.start()

    app.state.daemons = {d.name: d for d in daemons_list}
    log.info("crux_started", daemons=list(app.state.daemons.keys()))

    yield

    for d in reversed(daemons_list):
        await d.stop()

    kill_all_audio()
    await force_clear_all_locks(get_redis())
    cleanup_temp_files()
    await close_postgres()
    await close_redis()
    log.info("crux_stopped")


app = FastAPI(title="Crux", lifespan=lifespan)
app.include_router(health.router)
app.include_router(speak.router)
app.include_router(llm.router)
app.include_router(git_routes.router)
app.include_router(internal.router)


def main() -> None:
    s = get_settings()
    uvicorn.run(app, host=s.CRUX_HOST, port=s.CRUX_PORT, log_level=s.CRUX_LOG_LEVEL)


if __name__ == "__main__":
    main()
