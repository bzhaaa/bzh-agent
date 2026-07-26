"""Textual 全屏 TUI 测试。"""

import asyncio
from collections.abc import AsyncIterator
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from textual import events
from textual.widgets import Markdown, Static

from mewcode.agent import AgentMode
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, ProviderEvent, ProviderEventKind, TokenUsage
from mewcode.prompting import PromptEnvelope
from mewcode.session import ChatSession
from mewcode.tools import CommandApprovalRequest, ToolCall, ToolContext, ToolResult
from mewcode.tui import (
    AssistantMessage,
    CommandApprovalScreen,
    ComposerTextArea,
    ConversationView,
    MewCodeApp,
    ToolMessage,
    TranscriptEntry,
    TranscriptSnapshot,
    UserMessage,
    render_static_transcript,
)


class QueueProvider:
    def __init__(self, rounds: list[list[ProviderEvent | BaseException]]) -> None:
        self.rounds = rounds
        self.requests: list[tuple[ChatMessage, ...]] = []

    async def stream(self, request: PromptEnvelope) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request.messages)
        for item in self.rounds.pop(0):
            if isinstance(item, BaseException):
                raise item
            yield item


class BlockingProvider:
    def __init__(self) -> None:
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request: PromptEnvelope) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request.messages)
        yield ProviderEvent(ProviderEventKind.TEXT_DELTA, "部分")
        self.started.set()
        await self.release.wait()
        yield ProviderEvent(ProviderEventKind.TEXT_DELTA, "完成")
        yield ProviderEvent(ProviderEventKind.DONE)


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
                ProviderEvent(ProviderEventKind.THINKING_DELTA, "先想"),
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "你"),
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "好"),
                ProviderEvent(ProviderEventKind.DONE),
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
async def test_plan_do_mode_and_usage_status() -> None:
    provider = QueueProvider(
        [
            [
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "计划"),
                ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(5, 2, 3, 1)),
                ProviderEvent(ProviderEventKind.DONE),
            ],
            [
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "执行"),
                ProviderEvent(ProviderEventKind.TOKEN_USAGE, usage=TokenUsage(3, 1, 0, 2)),
                ProviderEvent(ProviderEventKind.DONE),
            ],
        ]
    )
    app = make_app(provider)
    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        composer.load_text("/plan 调查")
        await app.action_submit()
        await pilot.pause()
        assert app.mode == AgentMode.PLAN
        assert "Plan" in str(app.query_one("#composer-status", Static).content)
        composer.load_text("/do")
        await app.action_submit()
        await pilot.pause()
        status = str(app.query_one("#composer-status", Static).content)
        assert app.mode == AgentMode.NORMAL
        assert "Normal" in status
        assert "Token 4" in status
        assert "cache" not in status.lower()
        assert [entry.role for entry in app.transcript] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
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
            [
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "恢复"),
                ProviderEvent(ProviderEventKind.DONE),
            ],
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
async def test_invalid_stream_after_partial_text_adds_visible_status() -> None:
    provider = QueueProvider([[ProviderEvent(ProviderEventKind.TEXT_DELTA, "部分")]])
    app = make_app(provider)
    async with app.run_test() as pilot:
        await pilot.press("q", "enter")
        await pilot.pause()
        assert app.transcript[1].content == "部分"
        assert app.transcript[1].state == "error"
        assert app.transcript[2].role == "status"
        assert "无效" in app.transcript[2].content
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


class SuccessfulExecutor:
    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult(call.id, call.name, True, {"summary": "读取 1 行。"})


@pytest.mark.asyncio
async def test_tool_events_update_one_tool_message_and_final_answer(tmp_path: Path) -> None:
    call = ToolCall("tool-1", "read_file", '{"path":"demo.txt"}')
    provider = QueueProvider(
        [
            [
                ProviderEvent(ProviderEventKind.TOOL_CALL, tool_call=call),
                ProviderEvent(ProviderEventKind.DONE),
            ],
            [
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "读取完成"),
                ProviderEvent(ProviderEventKind.DONE),
            ],
        ]
    )
    session = ChatSession(provider, executor=SuccessfulExecutor(), context=ToolContext(tmp_path))
    app = MewCodeApp(session, profile_name="test", model="model")
    async with app.run_test() as pilot:
        await pilot.press("读", "取", "enter")
        await pilot.pause()
        assert len(app.query(ToolMessage)) == 1
        tool_entry = next(entry for entry in app.transcript if entry.role == "tool")
        assert tool_entry.tool_name == "read_file"
        assert tool_entry.state == "complete"
        assert tool_entry.content == "读取 1 行。"
        assistant_entry = next(entry for entry in app.transcript if entry.role == "assistant")
        assert assistant_entry.content == "读取完成"
        assert assistant_entry.state == "complete"
        assert [entry.role for entry in app.transcript] == ["user", "tool", "assistant"]
        app.exit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("y", True),
        ("enter", True),
        ("n", False),
        ("escape", False),
        ("#approve-command", True),
        ("#reject-command", False),
    ],
)
async def test_command_approval_keyboard_preserves_composer_draft(
    action: str, expected: bool
) -> None:
    app = make_app(QueueProvider([]))
    request = CommandApprovalRequest("printf ok", "/tmp/project", 30)
    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        composer.load_text("draft\nline")
        worker = app.run_worker(app.request_command_approval(request), exit_on_error=False)
        for _ in range(20):
            await pilot.pause()
            if isinstance(app.screen, CommandApprovalScreen):
                break
        screen = app.screen
        assert isinstance(screen, CommandApprovalScreen), repr(worker.error)
        assert "printf ok" in str(screen.query_one("#approval-command", Static).content)
        if action.startswith("#"):
            await pilot.click(action)
        else:
            await pilot.press(action)
        assert await worker.wait() is expected
        assert composer.text == "draft\nline"
        assert composer.has_focus
        app.exit()


def test_static_transcript_renders_bounded_tool_status() -> None:
    snapshot = TranscriptSnapshot(
        (
            TranscriptEntry("tool", "读取 2 行。", state="complete", tool_name="read_file"),
            TranscriptEntry("tool", "已拒绝。", state="rejected", tool_name="execute_command"),
        )
    )
    output = StringIO()
    render_static_transcript(snapshot, Console(file=output, force_terminal=False))
    rendered = output.getvalue()
    assert "read_file" in rendered
    assert "execute_command" in rendered
    assert "已拒绝" in rendered


@pytest.mark.asyncio
async def test_multiple_tool_iterations_continue_to_final_answer(tmp_path: Path) -> None:
    first = ToolCall("first", "read_file", '{"path":"demo.txt"}')
    second = ToolCall("second", "read_file", '{"path":"other.txt"}')
    provider = QueueProvider(
        [
            [
                ProviderEvent(ProviderEventKind.TOOL_CALL, tool_call=first),
                ProviderEvent(ProviderEventKind.DONE),
            ],
            [
                ProviderEvent(ProviderEventKind.TOOL_CALL, tool_call=second),
                ProviderEvent(ProviderEventKind.DONE),
            ],
            [
                ProviderEvent(ProviderEventKind.TEXT_DELTA, "全部完成"),
                ProviderEvent(ProviderEventKind.DONE),
            ],
        ]
    )
    app = MewCodeApp(
        ChatSession(provider, executor=SuccessfulExecutor(), context=ToolContext(tmp_path)),
        profile_name="test",
        model="model",
    )
    async with app.run_test() as pilot:
        await pilot.press("连", "续", "enter")
        await pilot.pause()
        second_entry = next(entry for entry in app.transcript if entry.call_id == "second")
        assert second_entry.state == "complete"
        assistant = next(entry for entry in app.transcript if entry.role == "assistant")
        assert assistant.content == "全部完成"
        assert [entry.role for entry in app.transcript] == [
            "user",
            "tool",
            "tool",
            "assistant",
        ]
        app.exit()
