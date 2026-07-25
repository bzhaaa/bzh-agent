"""经用户确认后异步执行 Shell 命令。"""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition
from mewcode.tools.errors import ToolError, ToolErrorCode

MAX_OUTPUT_BYTES = 64_000
PROCESS_GRACE_SECONDS = 1.0


class ExecuteCommandArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=20_000)
    timeout_seconds: float = Field(default=30, ge=1, le=300)


async def _read_bounded(stream: asyncio.StreamReader) -> tuple[bytes, bool]:
    collected = bytearray()
    truncated = False
    while chunk := await stream.read(8192):
        remaining = MAX_OUTPUT_BYTES - len(collected)
        if remaining > 0:
            collected.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(collected), truncated


async def _stop_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        await process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=PROCESS_GRACE_SECONDS)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


class ExecuteCommandTool:
    argument_model = ExecuteCommandArguments
    requires_approval = True
    definition = ToolDefinition(
        "execute_command",
        "在项目根目录执行完整 Shell 命令；每次执行前都需要用户确认。",
        ExecuteCommandArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: ExecuteCommandArguments, context: ToolContext
    ) -> dict[str, object]:
        try:
            process = await asyncio.create_subprocess_shell(
                arguments.command,
                cwd=context.project_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, ValueError) as error:
            raise ToolError(ToolErrorCode.EXECUTION_FAILED, "命令进程启动失败。") from error
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(_read_bounded(process.stdout))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr))
        try:
            async with asyncio.timeout(arguments.timeout_seconds):
                await process.wait()
                stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except TimeoutError as error:
            await _stop_process_group(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise ToolError(ToolErrorCode.TIMEOUT, "命令执行超时，进程组已终止。") from error
        except asyncio.CancelledError:
            await _stop_process_group(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        stdout_bytes, stdout_truncated = stdout
        stderr_bytes, stderr_truncated = stderr
        return {
            "command": arguments.command,
            "cwd": ".",
            "exit_code": process.returncode,
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "summary": f"命令执行完成，退出码 {process.returncode}。",
        }
