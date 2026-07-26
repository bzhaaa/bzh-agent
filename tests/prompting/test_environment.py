"""安全环境采集测试。"""

import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mewcode.agent import AgentMode
from mewcode.prompting import EnvironmentCollector


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def collector(home: Path) -> EnvironmentCollector:
    return EnvironmentCollector(
        now=lambda: datetime(2026, 7, 26, 10, tzinfo=UTC),
        platform_name=lambda: "TestOS",
        shell="/bin/zsh",
        home=home,
    )


@pytest.mark.asyncio
async def test_collects_clean_dirty_and_detached_git_state(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("one\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    clean = await collector(tmp_path).collect(root, AgentMode.NORMAL)
    assert clean.project_root == "~/project"
    assert clean.platform == "TestOS"
    assert clean.shell == "zsh"
    assert clean.current_date == "2026-07-26"
    assert clean.timezone == "UTC"
    assert clean.git_branch == "main"
    assert clean.git_dirty is False

    (root / "tracked.txt").write_text("two\n")
    dirty = await collector(tmp_path).collect(root, AgentMode.PLAN)
    assert dirty.git_dirty is True
    assert dirty.mode == AgentMode.PLAN

    git(root, "checkout", "--detach", "HEAD")
    detached = await collector(tmp_path).collect(root, AgentMode.NORMAL)
    assert detached.git_branch.startswith("detached:")


@pytest.mark.asyncio
async def test_non_git_environment_degrades_without_sensitive_values(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    result = await collector(tmp_path).collect(root, AgentMode.NORMAL)
    assert result.project_root == "~/project"
    assert result.git_branch == "unknown"
    assert result.git_dirty is None
    rendered = repr(result)
    assert os.environ.get("USER", "impossible-marker") not in rendered


@pytest.mark.asyncio
async def test_git_timeout_and_cancellation_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    executable = tmp_path / "bin" / "git"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nsleep 10\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable.parent))
    timed = EnvironmentCollector(git_timeout=0.02, home=tmp_path)
    result = await timed.collect(root, AgentMode.NORMAL)
    assert result.git_branch == "unknown"
    assert result.git_dirty is None

    blocking = EnvironmentCollector(git_timeout=60, home=tmp_path)
    task = asyncio.create_task(blocking.collect(root, AgentMode.NORMAL))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
