"""Textual 全屏 TUI 测试。"""

import asyncio
from collections.abc import AsyncIterator, Sequence
from io import StringIO

import pytest
from rich.console import Console
from textual import events
from textual.widgets import Markdown, Static

from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEvent, StreamEventKind
from mewcode.session import ChatSession
from mewcode.tui import (
    AssistantMessage,
    ComposerTextArea,
    ConversationView,
    MewCodeApp,
    TranscriptEntry,
    TranscriptSnapshot,
    UserMessage,
    render_static_transcript,
)


class QueueProvider:
    def __init__(self, rounds: list[list[StreamEvent | BaseException]]) -> None:
        self.rounds = rounds
        self.requests: list[tuple[ChatMessage, ...]] = []

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        self.requests.append(tuple(messages))
        for item in self.rounds.pop(0):
            if isinstance(item, BaseException):
                raise item
            yield item


class BlockingProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        self.requests.append(tuple(messages))
        yield StreamEvent(StreamEventKind.TEXT_DELTA, "部分")
        self.started.set()
        await self.release.wait()
        yield StreamEvent(StreamEventKind.TEXT_DELTA, "完成")
        yield StreamEvent(StreamEventKind.DONE)


def make_app(provider: object) -> MewCodeApp:
    return MewCodeApp(ChatSession(provider), profile_name="test", model="test-model")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 40), (44, 16)])
async def test_fixed_layout_at_multiple_sizes(size: tuple[int, int]) -> None:
    app = make_app(QueueProvider([]))
    async with app.run_test(size=size) as pilot:
        conversation = app.query_one(ConversationView)
        composer = app.query_one(ComposerTextArea)
        assert conversation.region.bottom <= composer.region.y
        assert composer.region.bottom == size[1] - 1
        assert conversation.region.height > 0
        app.exit()
        await pilot.pause()


@pytest.mark.asyncio
async def test_enter_submits_and_streams_into_one_assistant_message() -> None:
    provider = QueueProvider(
        [
            [
                StreamEvent(StreamEventKind.THINKING_DELTA, "先想"),
                StreamEvent(StreamEventKind.TEXT_DELTA, "你"),
                StreamEvent(StreamEventKind.TEXT_DELTA, "好"),
                StreamEvent(StreamEventKind.DONE),
            ]
        ]
    )
    app = make_app(provider)
    async with app.run_test() as pilot:
        await pilot.press("你", "好", "enter")
        await pilot.pause()
        assert len(provider.requests) == 1
        assert len(app.transcript) == 2
        assert len(app.query(AssistantMessage)) == 1
        entry = app.transcript[1]
        assert entry.thinking == "先想"
        assert entry.content == "你好"
        assert entry.state == "complete"
        message = app.query_one(AssistantMessage)
        assert message.query_one("#thinking-content", Static).content == "先想"
        assert message.query_one("#answer-content", Markdown).source == "你好"
        assert app.query_one(ComposerTextArea).text == ""
        app.exit()


@pytest.mark.asyncio
async def test_alt_enter_inserts_newline_and_height_caps_at_six() -> None:
    app = make_app(QueueProvider([]))
    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        await pilot.press("a")
        assert composer.logical_height == 1
        for expected in range(2, 7):
            await pilot.press("alt+enter", "x")
            assert composer.logical_height == expected
        await pilot.press("alt+enter", "x")
        assert composer.logical_height == 6
        assert composer.text.count("\n") == 6
        assert composer.max_scroll_y > 0
        assert len(app.transcript) == 0
        app.action_cancel_or_clear()
        await pilot.pause()
        assert composer.text == ""
        assert composer.logical_height == 1
        app.exit()


@pytest.mark.asyncio
async def test_generating_keeps_draft_and_blocks_submission() -> None:
    provider = BlockingProvider()
    app = make_app(provider)
    async with app.run_test() as pilot:
        await pilot.press("q", "enter")
        await provider.started.wait()
        await pilot.press("d", "r", "a", "f", "t", "enter", "enter")
        assert app.is_generating
        assert app.query_one(ComposerTextArea).text == "draft"
        assert len(provider.requests) == 1
        assert len(app.transcript) == 2
        await pilot.press("ctrl+d")
        assert app.is_running
        provider.release.set()
        await pilot.pause()
        assert not app.is_generating
        assert app.query_one(ComposerTextArea).text == "draft"
        app.exit()


@pytest.mark.asyncio
async def test_ctrl_c_cancels_reply_without_committing_history() -> None:
    provider = BlockingProvider()
    session = ChatSession(provider)
    app = MewCodeApp(session, profile_name="test", model="model")
    async with app.run_test() as pilot:
        await pilot.press("q", "enter")
        await provider.started.wait()
        await pilot.press("d", "r", "a", "f", "t", "ctrl+c")
        await pilot.pause()
        assert not app.is_generating
        assert session.history == ()
        assert app.transcript[1].state == "cancelled"
        assert app.transcript[1].content == "已取消当前回复。"
        assert app.query_one("#answer-content", Markdown).source == "已取消当前回复。"
        assert app.query_one(ComposerTextArea).text == "draft"
        app.exit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_kind",
    [
        ProviderErrorKind.AUTHENTICATION,
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.CONNECTION,
        ProviderErrorKind.SERVER,
    ],
)
async def test_provider_error_keeps_draft_and_allows_next_round(
    error_kind: ProviderErrorKind,
) -> None:
    provider = QueueProvider(
        [
            [ProviderError(error_kind)],
            [StreamEvent(StreamEventKind.TEXT_DELTA, "恢复"), StreamEvent(StreamEventKind.DONE)],
        ]
    )
    session = ChatSession(provider)
    app = MewCodeApp(session, profile_name="test", model="model")
    async with app.run_test() as pilot:
        await pilot.press("f", "a", "i", "l", "enter")
        await pilot.press("n", "e", "x", "t")
        await pilot.pause()
        assert app.transcript[1].state == "error"
        assert app.transcript[1].content.startswith("请求失败：")
        assert "secret" not in app.transcript[1].content
        assert app.query_one(ComposerTextArea).text == "next"
        assert session.history == ()
        await pilot.press("enter")
        await pilot.pause()
        assert session.history == (
            ChatMessage("user", "next"),
            ChatMessage("assistant", "恢复"),
        )
        app.exit()


@pytest.mark.asyncio
async def test_ctrl_d_and_exit_return_snapshot_without_draft() -> None:
    app = make_app(QueueProvider([]))
    app.transcript.append(TranscriptEntry("user", "历史"))
    async with app.run_test() as pilot:
        await pilot.press("d", "r", "a", "f", "t", "ctrl+d")
        assert app.is_running
        assert app.query_one(ComposerTextArea).text == "draft"
        app.action_cancel_or_clear()
        await pilot.press("ctrl+d")
        await pilot.pause()
    assert app.return_value == TranscriptSnapshot((TranscriptEntry("user", "历史"),))

    exit_app = make_app(QueueProvider([]))
    async with exit_app.run_test() as pilot:
        await pilot.press("/", "e", "x", "i", "t", "enter")
        await pilot.pause()
    assert exit_app.return_value == TranscriptSnapshot()


def test_static_transcript_contains_history_but_not_draft_or_secret() -> None:
    snapshot = TranscriptSnapshot(
        (
            TranscriptEntry("user", "问题"),
            TranscriptEntry("assistant", "回答", "思考", "complete"),
            TranscriptEntry("assistant", "已取消当前回复。", state="cancelled"),
            TranscriptEntry("assistant", "请求失败：连接错误", state="error"),
        )
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=80)
    render_static_transcript(snapshot, console)
    rendered = output.getvalue()
    for expected in ["问题", "回答", "思考", "已取消", "请求失败"]:
        assert expected in rendered
    assert "draft-secret" not in rendered


def test_snapshot_copies_mutable_entries() -> None:
    app = make_app(QueueProvider([]))
    entry = TranscriptEntry("assistant", "原文")
    app.transcript.append(entry)
    snapshot = app._snapshot()
    entry.content = "修改后"
    assert snapshot.entries[0].content == "原文"


@pytest.mark.asyncio
async def test_conversation_follows_bottom_but_not_when_scrolled_up() -> None:
    app = make_app(QueueProvider([]))
    async with app.run_test(size=(60, 14)) as pilot:
        conversation = app.query_one(ConversationView)
        for index in range(20):
            entry = TranscriptEntry("user", f"第 {index} 条\n第二行")
            app.transcript.append(entry)
            await conversation.append_message(UserMessage(entry))
        await pilot.pause()
        conversation.scroll_end(animate=False)
        await pilot.pause()
        assert conversation.is_vertical_scroll_end
        conversation.post_message(
            events.MouseScrollUp(
                conversation,
                x=1,
                y=1,
                delta_x=0,
                delta_y=-1,
                button=0,
                shift=False,
                meta=False,
                ctrl=False,
            )
        )
        await pilot.pause()
        previous = conversation.scroll_y
        assert previous < conversation.max_scroll_y
        entry = TranscriptEntry("user", "新消息")
        await conversation.append_message(UserMessage(entry))
        await pilot.pause()
        assert conversation.scroll_y == previous
        conversation.scroll_end(animate=False)
        await pilot.pause()
        followed = TranscriptEntry("user", "跟随消息")
        await conversation.append_message(UserMessage(followed))
        await pilot.pause()
        assert conversation.is_vertical_scroll_end
        app.exit()
