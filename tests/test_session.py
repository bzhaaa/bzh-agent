"""ChatSession 的 Plan/Do、历史和取消测试。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mewcode.agent import AgentEventKind, AgentMode, AgentStopReason
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    ChatMessage,
    ProviderEvent,
    ProviderEventKind,
    UserMessage,
)
from mewcode.session import ChatSession
from mewcode.tools import ToolCall, ToolContext, ToolErrorCode, ToolResult


class QueueProvider:
    def __init__(self, rounds: list[list[ProviderEvent | Exception]]) -> None:
        self.rounds = rounds
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.tool_names: list[tuple[str, ...]] = []

    async def stream(self, messages, tools=()) -> AsyncIterator[ProviderEvent]:
        self.requests.append(tuple(messages))
        self.tool_names.append(tuple(tool.name for tool in tools))
        for item in self.rounds.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall, _context: ToolContext) -> ToolResult:
        self.calls.append(call)
        known = call.name in {
            "read_file",
            "write_file",
            "edit_file",
            "execute_command",
            "find_files",
            "search_code",
        }
        return ToolResult(
            call.id,
            call.name,
            known,
            {"summary": "完成"} if known else {},
            error_code=None if known else ToolErrorCode.UNKNOWN_TOOL,
            error_message=None if known else "未知工具。",
        )


def text_round(text: str) -> list[ProviderEvent]:
    return [
        ProviderEvent(ProviderEventKind.TEXT_DELTA, text),
        ProviderEvent(ProviderEventKind.DONE),
    ]


def tool_round(call_id: str, name: str) -> list[ProviderEvent]:
    return [
        ProviderEvent(
            ProviderEventKind.TOOL_CALL,
            tool_call=ToolCall(call_id, name, "{}"),
        ),
        ProviderEvent(ProviderEventKind.DONE),
    ]


async def collect(session: ChatSession, text: str):
    return [event async for event in session.stream_reply(text)]


@pytest.mark.asyncio
async def test_plan_stays_readonly_and_do_switches_to_all_tools(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            tool_round("read", "read_file"),
            text_round("计划完成"),
            tool_round("write", "write_file"),
            text_round("执行完成"),
        ]
    )
    executor = RecordingExecutor()
    session = ChatSession(provider, executor=executor, context=ToolContext(tmp_path))

    plan_events = await collect(session, "/plan 调查并修改")
    assert plan_events[0].kind == AgentEventKind.MODE_CHANGED
    assert plan_events[0].mode == AgentMode.PLAN
    assert session.mode == AgentMode.PLAN
    assert session.plan_ready
    assert provider.tool_names[:2] == [
        ("read_file", "find_files", "search_code"),
        ("read_file", "find_files", "search_code"),
    ]
    assert isinstance(provider.requests[0][-1], UserMessage)
    assert "只读 Plan Mode" in provider.requests[0][-1].content

    do_events = await collect(session, "/do")
    assert do_events[0].kind == AgentEventKind.MODE_CHANGED
    assert do_events[0].mode == AgentMode.NORMAL
    assert session.mode == AgentMode.NORMAL
    assert not session.plan_ready
    assert len(provider.tool_names[2]) == 6
    assert [call.name for call in executor.calls] == ["write_file"]


@pytest.mark.asyncio
async def test_plan_followup_remains_readonly(tmp_path: Path) -> None:
    provider = QueueProvider([text_round("初始计划"), text_round("更新计划")])
    session = ChatSession(provider, context=ToolContext(tmp_path))
    await collect(session, "/plan 调查")
    events = await collect(session, "请直接写文件")
    assert events[-1].stop_reason == AgentStopReason.COMPLETED
    assert session.mode == AgentMode.PLAN
    assert session.plan_ready
    assert provider.tool_names[-1] == ("read_file", "find_files", "search_code")
    assert "继续在只读 Plan Mode" in provider.requests[-1][-1].content


@pytest.mark.asyncio
async def test_invalid_local_commands_do_not_request_provider(tmp_path: Path) -> None:
    provider = QueueProvider([])
    session = ChatSession(provider, context=ToolContext(tmp_path))
    invalid = await collect(session, "/plan")
    assert invalid[-1].stop_reason == AgentStopReason.INVALID_COMMAND
    no_plan = await collect(session, "/do")
    assert no_plan[-1].stop_reason == AgentStopReason.NO_PLAN
    assert provider.requests == []
    assert session.history == ()


@pytest.mark.asyncio
async def test_new_failed_plan_clears_old_plan_readiness(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            text_round("旧计划"),
            [ProviderError(ProviderErrorKind.CONNECTION)],
        ]
    )
    session = ChatSession(provider, context=ToolContext(tmp_path))
    await collect(session, "/plan 旧任务")
    assert session.plan_ready
    failed = await collect(session, "/plan 新任务")
    assert failed[-1].stop_reason == AgentStopReason.PROVIDER_ERROR
    assert not session.plan_ready
    no_plan = await collect(session, "/do")
    assert no_plan[-1].stop_reason == AgentStopReason.NO_PLAN
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_error_preserves_history_and_next_round_succeeds(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            [ProviderError(ProviderErrorKind.CONNECTION)],
            text_round("恢复"),
        ]
    )
    session = ChatSession(provider, context=ToolContext(tmp_path))
    failed = await collect(session, "失败")
    assert failed[-1].stop_reason == AgentStopReason.PROVIDER_ERROR
    assert session.history == ()
    recovered = await collect(session, "继续")
    assert recovered[-1].stop_reason == AgentStopReason.COMPLETED
    assert [message.role for message in session.history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_cancel_current_and_reject_parallel_run(tmp_path: Path) -> None:
    started = asyncio.Event()

    class BlockingProvider:
        async def stream(self, _messages, _tools=()) -> AsyncIterator[ProviderEvent]:
            yield ProviderEvent(ProviderEventKind.TEXT_DELTA, "部分")
            started.set()
            await asyncio.Event().wait()

    session = ChatSession(BlockingProvider(), context=ToolContext(tmp_path))

    async def first():
        return await collect(session, "第一个")

    task = asyncio.create_task(first())
    await started.wait()
    with pytest.raises(RuntimeError, match="正在执行"):
        await collect(session, "第二个")
    session.cancel_current()
    session.cancel_current()
    events = await task
    assert events[-1].stop_reason == AgentStopReason.CANCELLED
    assert session.history == ()
