"""按工具安全策略分段执行同批调用。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from mewcode.agent.control import AgentRunControl
from mewcode.tools.base import ToolCall, ToolContext, ToolExecutionPolicy, ToolResult
from mewcode.tools.errors import ToolErrorCode
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolSegmentResult:
    calls: tuple[ToolCall, ...]
    results: tuple[ToolResult, ...]


class ToolScheduler:
    def __init__(self, registry: ToolRegistry, executor: ToolExecutor) -> None:
        self.registry = registry
        self.executor = executor

    def has_tool(self, name: str) -> bool:
        return self.registry.get(name) is not None

    def segments(self, calls: Sequence[ToolCall]) -> tuple[tuple[ToolCall, ...], ...]:
        """按原顺序生成只读并发段、副作用单调用段和未知边界。"""

        result: list[tuple[ToolCall, ...]] = []
        read_segment: list[ToolCall] = []
        for call in calls:
            tool = self.registry.get(call.name)
            policy = getattr(tool, "policy", None)
            if policy == ToolExecutionPolicy.PARALLEL_READ:
                read_segment.append(call)
                continue
            if read_segment:
                result.append(tuple(read_segment))
                read_segment = []
            result.append((call,))
        if read_segment:
            result.append(tuple(read_segment))
        return tuple(result)

    @staticmethod
    def _cancelled(call: ToolCall) -> ToolResult:
        return ToolResult(
            call.id,
            call.name,
            False,
            {},
            error_code=ToolErrorCode.CANCELLED,
            error_message="工具调用因用户取消而未完成。",
        )

    async def _run_segment(
        self,
        calls: tuple[ToolCall, ...],
        context: ToolContext,
        control: AgentRunControl,
    ) -> tuple[tuple[ToolResult, ...], bool]:
        if control.is_cancelled():
            return tuple(self._cancelled(call) for call in calls), True
        tasks = [asyncio.create_task(self.executor.execute(call, context)) for call in calls]
        cancel_task = asyncio.create_task(control.wait_cancelled())
        try:
            pending = set(tasks)
            while pending:
                done, _ = await asyncio.wait(
                    (*pending, cancel_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done:
                    break
                pending.difference_update(done)
            if not pending:
                return tuple(task.result() for task in tasks), False

            # 取消信号胜出时仍保留已经完成的真实结果。
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            results = tuple(
                task.result()
                if task.done() and not task.cancelled() and task.exception() is None
                else self._cancelled(call)
                for call, task in zip(calls, tasks, strict=True)
            )
            return results, True
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    async def execute(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
        control: AgentRunControl,
    ) -> AsyncIterator[ToolSegmentResult]:
        segments = self.segments(calls)
        for segment_index, segment in enumerate(segments):
            results, cancelled = await self._run_segment(segment, context, control)
            yield ToolSegmentResult(segment, results)
            if not cancelled:
                continue
            for future in segments[segment_index + 1 :]:
                yield ToolSegmentResult(
                    future,
                    tuple(self._cancelled(call) for call in future),
                )
            return
