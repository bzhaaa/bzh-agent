"""多工具分段、并发、排序和取消测试。"""

import asyncio
import time
from pathlib import Path

import pytest

from mewcode.agent import AgentRunControl, ToolScheduler
from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolExecutionPolicy,
    ToolResult,
    create_default_registry,
)


class RecordingExecutor:
    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.delays = delays or {}
        self.started: dict[str, float] = {}
        self.finished: dict[str, float] = {}
        self.signals: dict[str, asyncio.Event] = {}

    async def execute(self, call: ToolCall, _context: ToolContext) -> ToolResult:
        self.started[call.id] = time.monotonic()
        signal = self.signals.get(call.id)
        if signal is not None:
            signal.set()
        await asyncio.sleep(self.delays.get(call.id, 0))
        self.finished[call.id] = time.monotonic()
        success = call.id != "fail"
        return ToolResult(
            call.id,
            call.name,
            success,
            {"summary": call.id} if success else {},
            error_code=None if success else ToolErrorCode.EXECUTION_FAILED,
            error_message=None if success else "失败",
        )


def call(call_id: str, name: str) -> ToolCall:
    return ToolCall(call_id, name, "{}")


def test_registry_policies_subset_and_segments() -> None:
    registry = create_default_registry()
    assert registry.get("read_file").policy == ToolExecutionPolicy.PARALLEL_READ  # type: ignore[union-attr]
    readonly = registry.subset(("read_file", "find_files", "search_code"))
    assert [item.name for item in readonly.definitions()] == [
        "read_file",
        "find_files",
        "search_code",
    ]
    scheduler = ToolScheduler(registry, RecordingExecutor())  # type: ignore[arg-type]
    segments = scheduler.segments(
        [
            call("a", "read_file"),
            call("b", "find_files"),
            call("c", "write_file"),
            call("d", "read_file"),
            call("e", "search_code"),
            call("f", "edit_file"),
        ]
    )
    assert [[item.id for item in segment] for segment in segments] == [
        ["a", "b"],
        ["c"],
        ["d", "e"],
        ["f"],
    ]


@pytest.mark.asyncio
async def test_parallel_reads_serial_side_effects_and_result_order(tmp_path: Path) -> None:
    registry = create_default_registry()
    executor = RecordingExecutor({"a": 0.05, "b": 0.01, "c": 0.01})
    scheduler = ToolScheduler(registry, executor)  # type: ignore[arg-type]
    batches = [
        batch
        async for batch in scheduler.execute(
            [call("a", "read_file"), call("b", "find_files"), call("c", "write_file")],
            ToolContext(tmp_path),
            AgentRunControl(),
        )
    ]
    assert [[result.call_id for result in batch.results] for batch in batches] == [
        ["a", "b"],
        ["c"],
    ]
    assert executor.started["b"] < executor.finished["a"]
    assert executor.started["c"] >= max(executor.finished["a"], executor.finished["b"])


@pytest.mark.asyncio
async def test_failure_isolated_and_cancel_fills_remaining(tmp_path: Path) -> None:
    registry = create_default_registry()
    executor = RecordingExecutor({"slow": 60, "later": 0})
    slow_started = asyncio.Event()
    executor.signals["slow"] = slow_started
    scheduler = ToolScheduler(registry, executor)  # type: ignore[arg-type]
    control = AgentRunControl()
    calls = [
        call("fail", "read_file"),
        call("slow", "find_files"),
        call("later", "write_file"),
    ]

    async def collect():
        return [batch async for batch in scheduler.execute(calls, ToolContext(tmp_path), control)]

    task = asyncio.create_task(collect())
    await slow_started.wait()
    control.cancel()
    batches = await task
    results = [result for batch in batches for result in batch.results]
    assert results[0].error_code == ToolErrorCode.EXECUTION_FAILED
    assert results[1].error_code == ToolErrorCode.CANCELLED
    assert results[2].error_code == ToolErrorCode.CANCELLED
    assert "later" not in executor.started
