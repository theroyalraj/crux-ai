from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.config import get_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def tmp_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    init = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    if init.returncode != 0:
        pytest.skip(f"git init unavailable in this environment: {init.stderr}")
    subprocess.run(["git", "config", "user.email", "t@e.st"], check=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "T"], check=True, cwd=tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], check=True, cwd=tmp_path)
    subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path)
    monkeypatch.setenv("CRUX_GIT_REPO_PATH", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


async def test_run_git_rev_parse(tmp_git_repo: Path) -> None:
    from server.git.ops import run_git

    code, out, _ = await run_git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    assert code == 0
    assert out.strip() in ("main", "master")


async def test_is_dirty_clean(tmp_git_repo: Path) -> None:
    from server.git.ops import is_dirty

    assert await is_dirty() is False
