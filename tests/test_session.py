"""会话完整轮次测试。"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    AssistantMessage,
    ChatMessage,
    StreamEvent,
    StreamEventKind,
    ToolResultMessage,
    UserMessage,
)
from mewcode.session import ChatSession
from mewcode.tools import ToolCall, ToolContext, ToolErrorCode, ToolResult


class QueueProvider:
    def __init__(self, rounds: list[list[StreamEvent | Exception]]) -> None:
        self.rounds = rounds
        self.requests: list[tuple[ChatMessage, ...]] = []

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        self.requests.append(tuple(messages))
        for item in self.rounds.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item


async def collect(session: ChatSession, text: str) -> list[StreamEvent]:
    return [event async for event in session.stream_reply(text)]


@pytest.mark.asyncio
async def test_successful_multiturn_history_excludes_thinking() -> None:
    provider = QueueProvider(
        [
            [
                StreamEvent(StreamEventKind.THINKING_DELTA, "分析"),
                StreamEvent(StreamEventKind.TEXT_DELTA, "第一答"),
                StreamEvent(StreamEventKind.DONE),
            ],
            [
                StreamEvent(StreamEventKind.TEXT_DELTA, "第二答"),
                StreamEvent(StreamEventKind.DONE),
            ],
        ]
    )
    session = ChatSession(provider)
    await collect(session, "第一问")
    await collect(session, "第二问")
    assert session.history == (
        ChatMessage("user", "第一问"),
        ChatMessage("assistant", "第一答"),
        ChatMessage("user", "第二问"),
        ChatMessage("assistant", "第二答"),
    )
    assert provider.requests[1] == session.history[:3]


@pytest.mark.asyncio
async def test_failure_does_not_change_history_and_next_round_succeeds() -> None:
    provider = QueueProvider(
        [
            [
                StreamEvent(StreamEventKind.TEXT_DELTA, "部分"),
                ProviderError(ProviderErrorKind.CONNECTION),
            ],
            [StreamEvent(StreamEventKind.TEXT_DELTA, "成功"), StreamEvent(StreamEventKind.DONE)],
        ]
    )
    session = ChatSession(provider)
    with pytest.raises(ProviderError):
        await collect(session, "失败问题")
    assert session.history == ()
    await collect(session, "成功问题")
    assert session.history == (
        ChatMessage("user", "成功问题"),
        ChatMessage("assistant", "成功"),
    )


@pytest.mark.asyncio
async def test_cancelled_round_does_not_change_history() -> None:
    started = asyncio.Event()

    class BlockingProvider:
        async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
            yield StreamEvent(StreamEventKind.TEXT_DELTA, "部分")
            started.set()
            await asyncio.Event().wait()

    session = ChatSession(BlockingProvider())
    task = asyncio.create_task(collect(session, "取消问题"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.history == ()


@pytest.mark.asyncio
async def test_missing_done_is_invalid_stream() -> None:
    session = ChatSession(QueueProvider([[StreamEvent(StreamEventKind.TEXT_DELTA, "回答")]]))
    with pytest.raises(ProviderError) as caught:
        await collect(session, "问题")
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM
    assert session.history == ()


class RecordingExecutor:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.calls: list[ToolCall] = []
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        self.calls.append(call)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.success:
            return ToolResult(call.id, call.name, True, {"summary": "完成"})
        return ToolResult(
            call.id,
            call.name,
            False,
            {},
            error_code=ToolErrorCode.NOT_FOUND,
            error_message="不存在",
        )


def tool_event(call_id: str = "call-1", name: str = "read_file") -> StreamEvent:
    return StreamEvent(
        StreamEventKind.TOOL_CALL,
        tool_call=ToolCall(call_id, name, '{"path":"a.txt"}'),
    )


@pytest.mark.asyncio
async def test_successful_tool_round_executes_once_and_commits_full_history(
    tmp_path: Path,
) -> None:
    provider = QueueProvider(
        [
            [tool_event(), StreamEvent(StreamEventKind.DONE)],
            [
                StreamEvent(StreamEventKind.TEXT_DELTA, "已读取"),
                StreamEvent(StreamEventKind.DONE),
            ],
        ]
    )
    executor = RecordingExecutor()
    session = ChatSession(provider, executor=executor, context=ToolContext(tmp_path))
    events = await collect(session, "读取文件")
    assert [event.kind for event in events] == [
        StreamEventKind.TOOL_CALL,
        StreamEventKind.TOOL_RESULT,
        StreamEventKind.TEXT_DELTA,
        StreamEventKind.DONE,
    ]
    assert len(executor.calls) == 1
    assert len(provider.requests) == 2
    assert isinstance(session.history[0], UserMessage)
    assert isinstance(session.history[1], AssistantMessage)
    assert session.history[1].tool_calls == (executor.calls[0],)
    assert isinstance(session.history[2], ToolResultMessage)
    assert session.history[3] == AssistantMessage("已读取")


@pytest.mark.asyncio
async def test_tool_failure_is_reinjected_and_can_finish(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [tool_event(), StreamEvent(StreamEventKind.DONE)],
            [
                StreamEvent(StreamEventKind.TEXT_DELTA, "文件不存在"),
                StreamEvent(StreamEventKind.DONE),
            ],
        ]
    )
    session = ChatSession(
        provider, executor=RecordingExecutor(success=False), context=ToolContext(tmp_path)
    )
    await collect(session, "读取")
    assert isinstance(provider.requests[1][-1], ToolResultMessage)
    assert provider.requests[1][-1].result.error_code == ToolErrorCode.NOT_FOUND
    assert len(session.history) == 4


@pytest.mark.asyncio
async def test_multiple_tools_all_rejected_without_execution(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [
                tool_event("a"),
                tool_event("b", "write_file"),
                StreamEvent(StreamEventKind.DONE),
            ],
            [
                StreamEvent(StreamEventKind.TEXT_DELTA, "一次只能一个"),
                StreamEvent(StreamEventKind.DONE),
            ],
        ]
    )
    executor = RecordingExecutor()
    session = ChatSession(provider, executor=executor, context=ToolContext(tmp_path))
    events = await collect(session, "做两件事")
    results = [event.tool_result for event in events if event.tool_result is not None]
    assert executor.calls == []
    assert len(results) == 2
    assert all(result.error_code == ToolErrorCode.MULTIPLE_TOOLS for result in results)
    assert len(provider.requests) == 2
    assert len(session.history[1].tool_calls) == 2


@pytest.mark.asyncio
async def test_second_tool_call_hits_limit_without_third_request_or_history(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [tool_event(), StreamEvent(StreamEventKind.DONE)],
            [tool_event("second"), StreamEvent(StreamEventKind.DONE)],
        ]
    )
    executor = RecordingExecutor()
    session = ChatSession(provider, executor=executor, context=ToolContext(tmp_path))
    events = await collect(session, "连续调用")
    assert events[-1].kind == StreamEventKind.LIMIT_REACHED
    assert len(executor.calls) == 1
    assert len(provider.requests) == 2
    assert session.history == ()


@pytest.mark.asyncio
async def test_cancellation_during_tool_execution_rolls_back_history(tmp_path: Path) -> None:
    provider = QueueProvider([[tool_event(), StreamEvent(StreamEventKind.DONE)]])
    executor = RecordingExecutor()
    executor.release = asyncio.Event()
    session = ChatSession(provider, executor=executor, context=ToolContext(tmp_path))
    task = asyncio.create_task(collect(session, "取消工具"))
    await executor.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.history == ()


@pytest.mark.asyncio
async def test_file_side_effect_survives_second_stream_cancellation(tmp_path: Path) -> None:
    second_started = asyncio.Event()

    class Provider:
        def __init__(self) -> None:
            self.count = 0

        async def stream(self, messages) -> AsyncIterator[StreamEvent]:
            self.count += 1
            if self.count == 1:
                yield StreamEvent(
                    StreamEventKind.TOOL_CALL,
                    tool_call=ToolCall(
                        "write",
                        "write_file",
                        '{"path":"created.txt","content":"done"}',
                    ),
                )
                yield StreamEvent(StreamEventKind.DONE)
                return
            second_started.set()
            await asyncio.Event().wait()
            yield StreamEvent(StreamEventKind.DONE)

    session = ChatSession(Provider(), context=ToolContext(tmp_path))
    task = asyncio.create_task(collect(session, "写文件"))
    await second_started.wait()
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "done"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.history == ()
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "done"


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_command_approval_starts_nothing(
    tmp_path: Path,
) -> None:
    approval_started = asyncio.Event()

    async def wait_for_approval(_request):
        approval_started.set()
        await asyncio.Event().wait()
        return True

    provider = QueueProvider(
        [
            [
                StreamEvent(
                    StreamEventKind.TOOL_CALL,
                    tool_call=ToolCall(
                        "command",
                        "execute_command",
                        '{"command":"touch should-not-exist"}',
                    ),
                ),
                StreamEvent(StreamEventKind.DONE),
            ]
        ]
    )
    session = ChatSession(provider, context=ToolContext(tmp_path, wait_for_approval))
    task = asyncio.create_task(collect(session, "执行命令"))
    await approval_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (tmp_path / "should-not-exist").exists()
    assert session.history == ()


@pytest.mark.asyncio
async def test_empty_second_response_rolls_back_entire_tool_round(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [tool_event(), StreamEvent(StreamEventKind.DONE)],
            [StreamEvent(StreamEventKind.DONE)],
        ]
    )
    session = ChatSession(provider, executor=RecordingExecutor(), context=ToolContext(tmp_path))
    with pytest.raises(ProviderError) as caught:
        await collect(session, "空最终答复")
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM
    assert session.history == ()
