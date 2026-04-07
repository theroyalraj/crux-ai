from __future__ import annotations

import asyncio

import structlog

from server.git.ops import default_branch, repo_path

log = structlog.get_logger(__name__)


async def create_mr(title: str, body: str, base: str | None = None) -> str:
    b = (base or await default_branch()).strip()
    cwd = str(repo_path())
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "pr",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--base",
        b,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    out = out_b.decode(errors="replace").strip()
    err = err_b.decode(errors="replace")
    if proc.returncode != 0:
        log.warning("gh_pr_create_failed", err=err)
        raise RuntimeError(err or "gh pr create failed")
    return out
