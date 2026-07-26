"""流收集、事件模型和显式取消测试。"""

import asyncio
from collections.abc import AsyncIterator

import pytest

from mewcode.agent import (
    AgentEvent,
    AgentEventKind,
    AgentMode,
    AgentRunCancelled,
    AgentRunControl,
    AgentStopReason,
    StreamCollector,
)
from mewcode.agent.control import wait_with_control
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ProviderEvent, ProviderEventKind, TokenUsage
from mewcode.tools import ToolCall


async def event_source(events: list[ProviderEvent]) -> AsyncIterator[ProviderEvent]:
    for event in events:
        yield event


def test_usage_accumulates_and_unknown_propagates() -> None:
    known = TokenUsage(10, 4, 3, 2)
    assert known.total_tokens == 14
    assert known.accumulate(TokenUsage(3, 2, 1, 5)) == TokenUsage(13, 6, 4, 7)
    unknown = known.accumulate(TokenUsage(None, 2, 1, None))
    assert unknown == TokenUsage(None, 6, 4, None)
    assert unknown.total_tokens is None


def test_all_agent_event_kinds_are_constructible() -> None:
    for kind in AgentEventKind:
        event = AgentEvent(kind, mode=AgentMode.PLAN, stop_reason=AgentStopReason.COMPLETED)
        assert event.kind == kind
        assert event.mode == AgentMode.PLAN


@pytest.mark.asyncio
async def test_control_wait_race_and_repeat_cancel() -> None:
    control = AgentRunControl()
    finished = asyncio.create_task(asyncio.sleep(0, result="ok"))
    assert await wait_with_control(finished, control) == "ok"
    control.cancel()
    control.cancel()
    assert control.is_cancelled()
    blocked = asyncio.create_task(asyncio.sleep(60))
    with pytest.raises(AgentRunCancelled):
        await wait_with_control(blocked, control)
    assert blocked.cancelled()


@pytest.mark.asyncio
async def test_stream_is_forwarded_and_complete_response_is_collected() -> None:
    call = ToolCall("call-1", "read_file", '{"path":"a.txt"}')
    collector = StreamCollector(iteration=2, mode=AgentMode.NORMAL, control=AgentRunControl())
    events = [
        ProviderEvent(ProviderEventKind.THINKING_DELTA, "想"),
        ProviderEvent(ProviderEventKind.TEXT_DELTA, "先读取"),
        ProviderEvent(ProviderEventKind.TOOL_CALL, tool_call=call),
        ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(8, 3)),
        ProviderEvent(ProviderEventKind.DONE),
    ]
    forwarded = [event async for event in collector.consume(event_source(events))]
    assert [event.kind for event in forwarded] == [
        AgentEventKind.THINKING_DELTA,
        AgentEventKind.TEXT_DELTA,
        AgentEventKind.TOOL_CALL,
    ]
    assert all(event.iteration == 2 for event in forwarded)
    assert collector.response.content == "先读取"
    assert collector.response.tool_calls == (call,)
    assert collector.response.usage == TokenUsage(8, 3)


@pytest.mark.asyncio
async def test_missing_usage_becomes_unknown() -> None:
    collector = StreamCollector(iteration=1, mode=AgentMode.NORMAL, control=AgentRunControl())
    _ = [
        event
        async for event in collector.consume(
            event_source(
                [
                    ProviderEvent(ProviderEventKind.TEXT_DELTA, "答"),
                    ProviderEvent(ProviderEventKind.DONE),
                ]
            )
        )
    ]
    assert collector.response.usage == TokenUsage(None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events",
    [
        [ProviderEvent(ProviderEventKind.TEXT_DELTA, "答")],
        [
            ProviderEvent(ProviderEventKind.DONE),
            ProviderEvent(ProviderEventKind.DONE),
        ],
        [
            ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(1, 1)),
            ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(1, 1)),
            ProviderEvent(ProviderEventKind.DONE),
        ],
        [ProviderEvent(ProviderEventKind.TEXT_DELTA), ProviderEvent(ProviderEventKind.DONE)],
        [
            ProviderEvent(
                ProviderEventKind.TOOL_CALL,
                tool_call=ToolCall("call", "read_file", "{"),
            ),
            ProviderEvent(ProviderEventKind.DONE),
        ],
        [
            ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(-1, 2)),
            ProviderEvent(ProviderEventKind.DONE),
        ],
    ],
)
async def test_invalid_streams_are_rejected(events: list[ProviderEvent]) -> None:
    collector = StreamCollector(iteration=1, mode=AgentMode.NORMAL, control=AgentRunControl())
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in collector.consume(event_source(events))]
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM


@pytest.mark.asyncio
async def test_cancel_closes_blocked_stream() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    async def blocked() -> AsyncIterator[ProviderEvent]:
        try:
            started.set()
            await asyncio.Event().wait()
            yield ProviderEvent(ProviderEventKind.DONE)
        finally:
            closed.set()

    control = AgentRunControl()
    collector = StreamCollector(iteration=1, mode=AgentMode.NORMAL, control=control)

    async def consume() -> None:
        _ = [event async for event in collector.consume(blocked())]

    task = asyncio.create_task(consume())
    await started.wait()
    control.cancel()
    with pytest.raises(AgentRunCancelled):
        await task
    assert closed.is_set()
