"""命令工具确认、输出、超时和取消测试。"""

import asyncio
import json
from pathlib import Path

import pytest

from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolExecutor,
    create_default_registry,
)


@pytest.mark.asyncio
async def test_command_requires_approval_and_reports_both_streams(tmp_path: Path) -> None:
    requests = []

    async def approve(request):
        requests.append(request)
        return True

    executor = ToolExecutor(create_default_registry())
    call = ToolCall(
        "cmd",
        "execute_command",
        json.dumps({"command": "printf out; printf err >&2; exit 3", "timeout_seconds": 5}),
    )
    result = await executor.execute(call, ToolContext(tmp_path, approve))
    assert result.success
    assert result.content["exit_code"] == 3
    assert result.content["stdout"] == "out"
    assert result.content["stderr"] == "err"
    assert requests[0].cwd == str(tmp_path)
    assert requests[0].timeout_seconds == 5


@pytest.mark.asyncio
async def test_rejected_command_has_no_side_effect(tmp_path: Path) -> None:
    async def reject(_request):
        return False

    result = await ToolExecutor(create_default_registry()).execute(
        ToolCall("cmd", "execute_command", '{"command":"touch marker"}'),
        ToolContext(tmp_path, reject),
    )
    assert result.error_code == ToolErrorCode.USER_REJECTED
    assert not (tmp_path / "marker").exists()


@pytest.mark.asyncio
async def test_command_timeout_and_cancellation_stop_side_effects(tmp_path: Path) -> None:
    async def approve(_request):
        return True

    executor = ToolExecutor(create_default_registry())
    timeout = await executor.execute(
        ToolCall(
            "cmd",
            "execute_command",
            '{"command":"sleep 2; touch late", "timeout_seconds":1}',
        ),
        ToolContext(tmp_path, approve),
    )
    assert timeout.error_code == ToolErrorCode.TIMEOUT
    await asyncio.sleep(1.2)
    assert not (tmp_path / "late").exists()

    task = asyncio.create_task(
        executor.execute(
            ToolCall("cmd2", "execute_command", '{"command":"sleep 2; touch cancelled"}'),
            ToolContext(tmp_path, approve),
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)
    assert not (tmp_path / "cancelled").exists()


@pytest.mark.asyncio
async def test_command_output_is_bounded_and_marked(tmp_path: Path) -> None:
    async def approve(_request):
        return True

    result = await ToolExecutor(create_default_registry()).execute(
        ToolCall(
            "large",
            "execute_command",
            '{"command":"yes x | head -c 70000; yes e | head -c 70000 >&2"}',
        ),
        ToolContext(tmp_path, approve),
    )
    assert result.success
    assert len(result.content["stdout"].encode("utf-8")) == 64_000
    assert len(result.content["stderr"].encode("utf-8")) == 64_000
    assert result.content["stdout_truncated"] is True
    assert result.content["stderr_truncated"] is True


@pytest.mark.asyncio
async def test_each_command_gets_fresh_approval(tmp_path: Path) -> None:
    requests = []

    async def approve(request):
        requests.append(request)
        return True

    executor = ToolExecutor(create_default_registry())
    context = ToolContext(tmp_path, approve)
    call = ToolCall("same", "execute_command", '{"command":"printf ok"}')
    assert (await executor.execute(call, context)).success
    assert (await executor.execute(call, context)).success
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_command_start_failure_is_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def approve(_request):
        return True

    async def fail_start(*_args, **_kwargs):
        raise OSError("unsafe launch detail")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail_start)
    result = await ToolExecutor(create_default_registry()).execute(
        ToolCall("fail", "execute_command", '{"command":"echo never"}'),
        ToolContext(tmp_path, approve),
    )
    assert result.error_code == ToolErrorCode.EXECUTION_FAILED
    assert "unsafe launch detail" not in result.to_model_json()
