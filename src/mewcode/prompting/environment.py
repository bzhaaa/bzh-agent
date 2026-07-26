"""有界、脱敏且可取消的运行环境采集。"""

from __future__ import annotations

import asyncio
import os
import platform as platform_module
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from mewcode.models import AgentMode
from mewcode.prompting.models import EnvironmentSnapshot

GIT_TIMEOUT_SECONDS = 1.0
GIT_OUTPUT_LIMIT = 8192


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    collected = bytearray()
    while chunk := await stream.read(1024):
        remaining = limit - len(collected)
        if remaining > 0:
            collected.extend(chunk[:remaining])
    return bytes(collected)


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        await process.wait()
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=0.2)
    except TimeoutError:
        process.kill()
        await process.wait()


class EnvironmentCollector:
    """采集不包含环境变量列表或文件名的安全快照。"""

    def __init__(
        self,
        *,
        git_timeout: float = GIT_TIMEOUT_SECONDS,
        output_limit: int = GIT_OUTPUT_LIMIT,
        now: Callable[[], datetime] | None = None,
        platform_name: Callable[[], str] | None = None,
        shell: str | None = None,
        home: Path | None = None,
    ) -> None:
        self.git_timeout = git_timeout
        self.output_limit = output_limit
        self._now = now or (lambda: datetime.now().astimezone())
        self._platform_name = platform_name or platform_module.system
        self._shell = shell
        self._home = (home or Path.home()).resolve()

    async def _run_git(self, root: Path, *arguments: str) -> tuple[int, str] | None:
        process: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task[bytes] | None = None
        stderr_task: asyncio.Task[bytes] | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *arguments,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_task = asyncio.create_task(_read_bounded(process.stdout, self.output_limit))
            stderr_task = asyncio.create_task(_read_bounded(process.stderr, self.output_limit))
            async with asyncio.timeout(self.git_timeout):
                return_code = await process.wait()
                stdout, _stderr = await asyncio.gather(stdout_task, stderr_task)
            return return_code, stdout.decode("utf-8", errors="replace").strip()
        except asyncio.CancelledError:
            if process is not None:
                await _stop_process(process)
            if stdout_task is not None and stderr_task is not None:
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        except (TimeoutError, OSError, ValueError):
            if process is not None:
                await _stop_process(process)
            if stdout_task is not None and stderr_task is not None:
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            return None

    def _display_root(self, root: Path) -> str:
        try:
            relative = root.relative_to(self._home)
        except ValueError:
            return str(root)
        return "~" if not relative.parts else str(Path("~") / relative)

    async def collect(self, project_root: Path, mode: AgentMode) -> EnvironmentSnapshot:
        """环境失败时用 unknown 降级，不阻塞模型请求。"""

        root = await asyncio.to_thread(project_root.resolve)
        branch_result = await self._run_git(root, "symbolic-ref", "--short", "-q", "HEAD")
        branch = branch_result[1] if branch_result and branch_result[0] == 0 else "unknown"
        if branch == "unknown":
            detached = await self._run_git(root, "rev-parse", "--short", "HEAD")
            if detached and detached[0] == 0 and detached[1]:
                branch = f"detached:{detached[1][:16]}"
        dirty_result = await self._run_git(root, "status", "--porcelain")
        dirty = None if dirty_result is None or dirty_result[0] != 0 else bool(dirty_result[1])
        current = self._now()
        timezone = current.tzname() or current.strftime("UTC%z") or "unknown"
        shell_value = self._shell if self._shell is not None else os.environ.get("SHELL", "")
        shell = Path(shell_value).name if shell_value else "unknown"
        return EnvironmentSnapshot(
            project_root=self._display_root(root),
            platform=self._platform_name() or "unknown",
            shell=shell,
            current_date=current.date().isoformat(),
            timezone=timezone,
            git_branch=branch,
            git_dirty=dirty,
            mode=mode,
        )
