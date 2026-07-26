"""AgentRunner 循环、停止条件、用量和历史检查点测试。"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from mewcode.agent import (
    AgentEventKind,
    AgentMode,
    AgentRunControl,
    AgentRunner,
    AgentRunRequest,
    AgentStopReason,
    ToolScheduler,
)
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    ChatMessage,
    ProviderEvent,
    ProviderEventKind,
    TokenUsage,
    UserMessage,
)
from mewcode.prompting import PromptEnvelope, PromptPipeline
from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolResult,
    create_default_registry,
)


class QueueProvider:
    def __init__(self, rounds: list[list[ProviderEvent | Exception]]) -> None:
        self.rounds = rounds
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.tool_names: list[tuple[str, ...]] = []
        self.envelopes: list[PromptEnvelope] = []

    async def stream(self, request: PromptEnvelope) -> AsyncIterator[ProviderEvent]:
        self.envelopes.append(request)
        self.requests.append(request.messages)
        self.tool_names.append(tuple(tool.name for tool in request.tools))
        for item in self.rounds.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall, _context: ToolContext) -> ToolResult:
        self.calls.append(call)
        if call.name not in {
            "read_file",
            "find_files",
            "search_code",
            "write_file",
            "edit_file",
            "execute_command",
        }:
            return ToolResult(
                call.id,
                call.name,
                False,
                {},
                error_code=ToolErrorCode.UNKNOWN_TOOL,
                error_message="未知工具。",
            )
        return ToolResult(call.id, call.name, True, {"summary": "完成"})


class Sink:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []

    async def commit(self, messages: Sequence[ChatMessage]) -> None:
        self.messages.extend(messages)


def tool_round(call_id: str, name: str = "read_file", text: str = "") -> list[ProviderEvent]:
    events = []
    if text:
        events.append(ProviderEvent(ProviderEventKind.TEXT_DELTA, text))
    events.extend(
        [
            ProviderEvent(
                ProviderEventKind.TOOL_CALL,
                tool_call=ToolCall(call_id, name, "{}"),
            ),
            ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(2, 1)),
            ProviderEvent(ProviderEventKind.DONE),
        ]
    )
    return events


def text_round(text: str) -> list[ProviderEvent]:
    return [
        ProviderEvent(ProviderEventKind.TEXT_DELTA, text),
        ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(3, 2)),
        ProviderEvent(ProviderEventKind.DONE),
    ]


def build_runner(provider: QueueProvider, tmp_path: Path):
    registry = create_default_registry()
    readonly = registry.subset(("read_file", "find_files", "search_code"))
    executor = RecordingExecutor()
    runner = AgentRunner(
        provider,
        ToolScheduler(registry, executor),  # type: ignore[arg-type]
        ToolScheduler(readonly, executor),  # type: ignore[arg-type]
        ToolContext(tmp_path),
        PromptPipeline(),
    )
    return runner, executor


async def run_events(runner: AgentRunner, sink: Sink, *, maximum: int = 10):
    request = AgentRunRequest(
        (),
        UserMessage("任务"),
        AgentMode.NORMAL,
        AgentRunControl(),
        sink,
        max_iterations=maximum,
    )
    return [event async for event in runner.run(request)]


@pytest.mark.asyncio
async def test_text_fast_path_and_usage(tmp_path: Path) -> None:
    provider = QueueProvider([text_round("完成")])
    runner, executor = build_runner(provider, tmp_path)
    sink = Sink()
    events = await run_events(runner, sink)
    assert len(provider.requests) == 1
    assert executor.calls == []
    assert [message.role for message in sink.messages] == ["user", "assistant"]
    assert events[-1].stop_reason == AgentStopReason.COMPLETED
    usage = next(event.usage for event in events if event.kind == AgentEventKind.TOKEN_USAGE)
    assert usage is not None and usage.cumulative == TokenUsage(3, 2)


@pytest.mark.asyncio
async def test_multi_iteration_loop_and_checkpoints(tmp_path: Path) -> None:
    provider = QueueProvider(
        [tool_round("a", text="先读"), tool_round("b", "search_code"), text_round("完成")]
    )
    runner, executor = build_runner(provider, tmp_path)
    sink = Sink()
    events = await run_events(runner, sink)
    assert [call.id for call in executor.calls] == ["a", "b"]
    assert len(provider.requests) == 3
    assert [message.role for message in sink.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert events[-1].stop_reason == AgentStopReason.COMPLETED
    usage_events = [event.usage for event in events if event.kind == AgentEventKind.TOKEN_USAGE]
    assert usage_events[-1] is not None
    assert usage_events[-1].cumulative == TokenUsage(7, 4)


@pytest.mark.asyncio
async def test_iteration_limit_executes_last_batch(tmp_path: Path) -> None:
    provider = QueueProvider([tool_round("a"), tool_round("b")])
    runner, executor = build_runner(provider, tmp_path)
    events = await run_events(runner, Sink(), maximum=2)
    assert len(provider.requests) == 2
    assert [call.id for call in executor.calls] == ["a", "b"]
    assert events[-1].stop_reason == AgentStopReason.ITERATION_LIMIT


@pytest.mark.asyncio
async def test_unknown_limit_and_valid_reset(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            tool_round("u1", "missing"),
            tool_round("ok", "read_file"),
            tool_round("u2", "missing"),
            tool_round("u3", "missing"),
        ]
    )
    runner, _ = build_runner(provider, tmp_path)
    events = await run_events(runner, Sink())
    assert len(provider.requests) == 4
    assert events[-1].stop_reason == AgentStopReason.UNKNOWN_TOOL_LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (ProviderErrorKind.CONNECTION, AgentStopReason.PROVIDER_ERROR),
        (ProviderErrorKind.INVALID_STREAM, AgentStopReason.INVALID_STREAM),
    ],
)
async def test_provider_errors_become_stop_events(
    tmp_path: Path,
    kind: ProviderErrorKind,
    reason: AgentStopReason,
) -> None:
    provider = QueueProvider([[ProviderError(kind)]])
    runner, _ = build_runner(provider, tmp_path)
    events = await run_events(runner, Sink())
    assert events[-1].stop_reason == reason
    usage = next(event.usage for event in events if event.kind == AgentEventKind.TOKEN_USAGE)
    assert usage is not None and usage.request == TokenUsage(None, None)


@pytest.mark.asyncio
async def test_provider_error_preserves_usage_seen_before_failure(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [
                ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(9, 2)),
                ProviderError(ProviderErrorKind.CONNECTION),
            ]
        ]
    )
    runner, _ = build_runner(provider, tmp_path)
    events = await run_events(runner, Sink())
    usage = next(event.usage for event in events if event.kind == AgentEventKind.TOKEN_USAGE)
    assert usage is not None and usage.request == TokenUsage(9, 2)


@pytest.mark.asyncio
async def test_cancel_during_model_stream_discards_partial_response(tmp_path: Path) -> None:
    started = asyncio.Event()

    class BlockingProvider:
        async def stream(self, _request: PromptEnvelope) -> AsyncIterator[ProviderEvent]:
            yield ProviderEvent(ProviderEventKind.TEXT_DELTA, "部分")
            started.set()
            await asyncio.Event().wait()

    registry = create_default_registry()
    readonly = registry.subset(("read_file", "find_files", "search_code"))
    executor = RecordingExecutor()
    runner = AgentRunner(
        BlockingProvider(),  # type: ignore[arg-type]
        ToolScheduler(registry, executor),  # type: ignore[arg-type]
        ToolScheduler(readonly, executor),  # type: ignore[arg-type]
        ToolContext(tmp_path),
        PromptPipeline(),
    )
    sink = Sink()
    control = AgentRunControl()
    request = AgentRunRequest((), UserMessage("任务"), AgentMode.NORMAL, control, sink)

    async def collect():
        return [event async for event in runner.run(request)]

    task = asyncio.create_task(collect())
    await started.wait()
    control.cancel()
    events = await task
    assert sink.messages == []
    assert events[-1].stop_reason == AgentStopReason.CANCELLED


@pytest.mark.asyncio
async def test_cancel_during_tools_commits_cancelled_checkpoint(tmp_path: Path) -> None:
    started = asyncio.Event()

    class BlockingExecutor:
        async def execute(self, _call: ToolCall, _context: ToolContext) -> ToolResult:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("不可到达")

    provider = QueueProvider([tool_round("slow")])
    registry = create_default_registry()
    readonly = registry.subset(("read_file", "find_files", "search_code"))
    executor = BlockingExecutor()
    runner = AgentRunner(
        provider,
        ToolScheduler(registry, executor),  # type: ignore[arg-type]
        ToolScheduler(readonly, executor),  # type: ignore[arg-type]
        ToolContext(tmp_path),
        PromptPipeline(),
    )
    sink = Sink()
    control = AgentRunControl()
    request = AgentRunRequest((), UserMessage("任务"), AgentMode.NORMAL, control, sink)

    async def collect():
        return [event async for event in runner.run(request)]

    task = asyncio.create_task(collect())
    await started.wait()
    control.cancel()
    events = await task
    assert [message.role for message in sink.messages] == ["user", "assistant", "tool"]
    assert sink.messages[-1].result.error_code == ToolErrorCode.CANCELLED  # type: ignore[attr-defined]
    assert events[-1].stop_reason == AgentStopReason.CANCELLED


@pytest.mark.asyncio
async def test_prompt_reminder_frequency_follows_runner_iterations(tmp_path: Path) -> None:
    provider = QueueProvider([tool_round(f"call-{index}") for index in range(1, 11)])
    runner, _ = build_runner(provider, tmp_path)
    events = await run_events(runner, Sink(), maximum=10)
    supplements = [request.prompt.supplements[0] for request in provider.envelopes]
    assert len(supplements) == 10
    assert ["持续调查、执行并验证" in item for item in supplements] == [
        True,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
    ]
    assert events[-1].stop_reason == AgentStopReason.ITERATION_LIMIT


@pytest.mark.asyncio
async def test_cancel_during_prompt_build_skips_provider_request(tmp_path: Path) -> None:
    started = asyncio.Event()

    class BlockingPipeline:
        async def build(self, **_kwargs):
            started.set()
            await asyncio.Event().wait()

    provider = QueueProvider([])
    registry = create_default_registry()
    readonly = registry.subset(("read_file", "find_files", "search_code"))
    executor = RecordingExecutor()
    runner = AgentRunner(
        provider,
        ToolScheduler(registry, executor),  # type: ignore[arg-type]
        ToolScheduler(readonly, executor),  # type: ignore[arg-type]
        ToolContext(tmp_path),
        BlockingPipeline(),  # type: ignore[arg-type]
    )
    control = AgentRunControl()
    request = AgentRunRequest((), UserMessage("任务"), AgentMode.NORMAL, control, Sink())
    task = asyncio.create_task(
        anext(event async for event in runner.run(request) if event.kind == AgentEventKind.STOPPED)
    )
    await started.wait()
    control.cancel()
    stopped = await task
    assert stopped.stop_reason == AgentStopReason.CANCELLED
    assert provider.requests == []
