"""MewCode Textual 全屏终端界面。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Markdown, Static, TextArea
from textual.worker import Worker

from mewcode.errors import ProviderError
from mewcode.models import StreamEventKind
from mewcode.session import ChatSession

TranscriptRole = Literal["user", "assistant", "status"]
TranscriptState = Literal["streaming", "complete", "cancelled", "error"]


@dataclass(slots=True)
class TranscriptEntry:
    """一条 UI 对话记录，与模型上下文相互独立。"""

    role: TranscriptRole
    content: str = ""
    thinking: str = ""
    state: TranscriptState = "complete"


@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    """退出全屏界面时生成的不可变记录。"""

    entries: tuple[TranscriptEntry, ...] = ()


class UserMessage(Vertical):
    """用户消息。"""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        margin: 1 1 0 1;
        padding: 0 1;
        border-left: thick $accent;
    }
    UserMessage .message-label {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }
    UserMessage .user-content {
        height: auto;
    }
    """

    def __init__(self, entry: TranscriptEntry) -> None:
        super().__init__(classes="user-message")
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Static("你", classes="message-label")
        yield Static(self.entry.content, classes="user-content")


class AssistantMessage(Vertical):
    """可被流事件持续更新的模型消息。"""

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        margin: 1 1 0 1;
        padding: 0 1;
    }
    AssistantMessage .message-label {
        height: 1;
        color: $accent;
        text-style: bold;
    }
    AssistantMessage .thinking-label {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }
    AssistantMessage .thinking-content {
        height: auto;
        color: $text-muted;
    }
    AssistantMessage Markdown {
        height: auto;
    }
    AssistantMessage.cancelled, AssistantMessage.error {
        color: $warning;
    }
    """

    def __init__(self, entry: TranscriptEntry) -> None:
        super().__init__(classes="assistant-message")
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Static("MewCode", classes="message-label")
        yield Static("思考", classes="thinking-label", id="thinking-label")
        yield Static(self.entry.thinking, classes="thinking-content", id="thinking-content")
        yield Markdown(self.entry.content or "…", id="answer-content")

    def on_mount(self) -> None:
        self._set_thinking_visibility()

    def _set_thinking_visibility(self) -> None:
        visible = bool(self.entry.thinking)
        self.query_one("#thinking-label", Static).display = visible
        self.query_one("#thinking-content", Static).display = visible

    async def refresh_entry(self) -> None:
        """把 entry 当前内容同步到既有组件。"""

        self.set_classes(f"assistant-message {self.entry.state}")
        self.query_one("#thinking-content", Static).update(self.entry.thinking)
        self._set_thinking_visibility()
        answer = self.entry.content or ("…" if self.entry.state == "streaming" else "")
        await self.query_one("#answer-content", Markdown).update(answer)


class StatusMessage(Static):
    """非模型状态消息。"""

    DEFAULT_CSS = """
    StatusMessage {
        height: auto;
        margin: 1 2 0 2;
        color: $warning;
    }
    """

    def __init__(self, entry: TranscriptEntry) -> None:
        super().__init__(entry.content, classes=f"status-message {entry.state}")
        self.entry = entry


class ConversationView(VerticalScroll):
    """支持条件自动跟随的历史消息区域。"""

    DEFAULT_CSS = """
    ConversationView {
        height: 1fr;
        width: 100%;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }
    """

    async def append_message(self, widget: UserMessage | AssistantMessage | StatusMessage) -> None:
        follow = self.is_vertical_scroll_end
        await self.mount(widget)
        if follow:
            self._follow_after_layout()

    async def refresh_message(self, widget: AssistantMessage) -> None:
        follow = self.is_vertical_scroll_end
        await widget.refresh_entry()
        if follow:
            self._follow_after_layout()

    def _follow_after_layout(self) -> None:
        """等待内容重排后再使用新的 max_scroll_y。"""

        self.refresh(layout=True)
        self.call_after_refresh(self._scroll_to_latest)

    def _scroll_to_latest(self) -> None:
        self.scroll_end(animate=False, immediate=True, force=True)


class ComposerTextArea(TextArea):
    """Enter 提交、Alt+Enter 换行的多行输入框。"""

    def __init__(self) -> None:
        super().__init__(
            id="composer",
            soft_wrap=True,
            show_line_numbers=False,
            tab_behavior="focus",
            placeholder="输入消息",
        )
        self.logical_height = 1

    async def on_key(self, event: events.Key) -> None:
        if event.key == "alt+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n", self.cursor_location)
        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            await self.app.action_submit()

    def update_height(self) -> None:
        """按显式换行数把可见输入行限制在 1-6 行。"""

        self.logical_height = min(max(self.text.count("\n") + 1, 1), 6)
        self.styles.height = self.logical_height + 2


class MewCodeApp(App[TranscriptSnapshot]):
    """固定历史区和底部输入框的全屏应用。"""

    BINDINGS = [
        Binding("ctrl+c", "cancel_or_clear", priority=True, show=False),
        Binding("ctrl+d", "exit_if_empty", priority=True, show=False),
    ]

    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }
    #app-title {
        height: 1;
        padding: 0 1;
        color: $accent;
        text-style: bold;
        background: $panel;
    }
    #composer-wrap {
        height: auto;
        width: 100%;
        border-top: solid $border;
        padding: 0 1;
        background: $panel;
    }
    #composer {
        height: 3;
        width: 100%;
        border: round $accent;
        padding: 0 1;
    }
    #composer-status {
        height: 1;
        width: 100%;
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, session: ChatSession, *, profile_name: str, model: str) -> None:
        super().__init__()
        self.session = session
        self.profile_name = profile_name
        self.model = model
        self.transcript: list[TranscriptEntry] = []
        self.is_generating = False
        self.reply_worker: Worker[None] | None = None
        self.current_entry: TranscriptEntry | None = None
        self.current_message: AssistantMessage | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"MewCode  {self.profile_name} · {self.model}", id="app-title")
        yield ConversationView(id="conversation")
        with Container(id="composer-wrap"):
            yield ComposerTextArea()
            yield Static("就绪", id="composer-status")

    def on_mount(self) -> None:
        self.query_one(ComposerTextArea).focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if isinstance(event.text_area, ComposerTextArea):
            event.text_area.update_height()

    def _snapshot(self) -> TranscriptSnapshot:
        return TranscriptSnapshot(tuple(replace(entry) for entry in self.transcript))

    async def action_submit(self) -> None:
        if self.is_generating:
            return
        composer = self.query_one(ComposerTextArea)
        user_input = composer.text.strip()
        if not user_input:
            return
        if user_input == "/exit":
            self.exit(self._snapshot())
            return

        composer.load_text("")
        composer.update_height()
        user_entry = TranscriptEntry("user", content=user_input)
        assistant_entry = TranscriptEntry("assistant", state="streaming")
        self.transcript.extend((user_entry, assistant_entry))

        conversation = self.query_one(ConversationView)
        await conversation.append_message(UserMessage(user_entry))
        assistant_message = AssistantMessage(assistant_entry)
        await conversation.append_message(assistant_message)

        self.is_generating = True
        self.current_entry = assistant_entry
        self.current_message = assistant_message
        self.query_one("#composer-status", Static).update("正在生成")
        self.reply_worker = self.run_worker(
            self._consume_reply(user_input, assistant_entry, assistant_message),
            name="reply",
            group="reply",
            exclusive=True,
            exit_on_error=False,
        )

    async def _consume_reply(
        self,
        user_input: str,
        entry: TranscriptEntry,
        message: AssistantMessage,
    ) -> None:
        conversation = self.query_one(ConversationView)
        try:
            async for event in self.session.stream_reply(user_input):
                if event.kind == StreamEventKind.THINKING_DELTA:
                    entry.thinking += event.delta
                elif event.kind == StreamEventKind.TEXT_DELTA:
                    entry.content += event.delta
                elif event.kind == StreamEventKind.DONE:
                    entry.state = "complete"
                await conversation.refresh_message(message)
        except asyncio.CancelledError:
            entry.state = "cancelled"
            entry.thinking = ""
            entry.content = "已取消当前回复。"
            await conversation.refresh_message(message)
        except ProviderError as error:
            entry.state = "error"
            entry.thinking = ""
            entry.content = f"请求失败：{error}"
            await conversation.refresh_message(message)
        finally:
            self.is_generating = False
            self.current_entry = None
            self.current_message = None
            self.reply_worker = None
            self.query_one("#composer-status", Static).update("就绪")
            self.query_one(ComposerTextArea).focus()

    def action_cancel_or_clear(self) -> None:
        if self.is_generating and self.reply_worker is not None:
            self.reply_worker.cancel()
            return
        composer = self.query_one(ComposerTextArea)
        composer.load_text("")
        composer.update_height()

    def action_exit_if_empty(self) -> None:
        composer = self.query_one(ComposerTextArea)
        if not self.is_generating and not composer.text:
            self.exit(self._snapshot())


def render_static_transcript(snapshot: TranscriptSnapshot | None, console: Console) -> None:
    """在备用屏幕恢复后打印本次 UI 对话记录。"""

    if snapshot is None or not snapshot.entries:
        return
    console.print("[bold cyan]MewCode 对话记录[/bold cyan]")
    for entry in snapshot.entries:
        if entry.role == "user":
            console.print("[bold]你[/bold]")
            console.print(entry.content)
        elif entry.role == "assistant":
            if entry.thinking:
                console.print("[dim bold]思考[/dim bold]")
                console.print(entry.thinking, style="dim")
            console.print("[bold cyan]MewCode[/bold cyan]")
            console.print(RichMarkdown(entry.content))
        else:
            console.print(entry.content, style="yellow")
