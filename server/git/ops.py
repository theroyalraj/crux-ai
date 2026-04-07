from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from server.config import get_settings

log = structlog.get_logger(__name__)

_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent


def repo_path() -> Path:
    s = get_settings()
    p = Path(s.CRUX_GIT_REPO_PATH)
    if p.is_absolute():
        return p.resolve()
    return (_SERVER_ROOT / p).resolve()


async def run_git(*args: str, check: bool = True) -> tuple[int, str, str]:
    cwd = str(repo_path())
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    out = out_b.decode(errors="replace")
    err = err_b.decode(errors="replace")
    if check and proc.returncode != 0:
        log.warning("git_failed", args=list(args), code=proc.returncode, err=err)
        raise RuntimeError(err or out or "git failed")
    return proc.returncode, out, err


async def is_dirty() -> bool:
    code, out, _ = await run_git("status", "--porcelain", check=False)
    if code != 0:
        return False
    return bool(out.strip())


async def default_branch() -> str:
    s = get_settings()
    if s.CRUX_GIT_TARGET_BRANCH.strip():
        return s.CRUX_GIT_TARGET_BRANCH.strip()
    code, out, _ = await run_git("remote", "show", "origin", check=False)
    if code == 0 and "HEAD branch:" in out:
        for line in out.splitlines():
            if "HEAD branch:" in line:
                return line.split("HEAD branch:")[-1].strip()
    code, out, _ = await run_git("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    if code == 0 and out.strip():
        ref = out.strip()
        if ref.endswith("/main"):
            return "main"
        if ref.endswith("/master"):
            return "master"
        return ref.rsplit("/", 1)[-1]
    return "main"
