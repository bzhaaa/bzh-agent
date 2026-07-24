"""会话完整轮次测试。"""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEvent, StreamEventKind
from mewcode.session import ChatSession


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
