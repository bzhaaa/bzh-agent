"""MewCode Textual 全屏终端界面。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from typing import Literal

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static, TextArea
from textual.worker import Worker

from mewcode.agent import AgentEventKind, AgentMode, AgentStopReason
from mewcode.session import ChatSession
from mewcode.tools import CommandApprovalRequest, ToolCall, ToolErrorCode

TranscriptRole = Literal["user", "assistant", "tool", "status"]
TranscriptState = Literal[
    "streaming", "pending", "approved", "rejected", "complete", "cancelled", "error"
]


@dataclass(slots=True)
class TranscriptEntry:
    """一条 UI 对话记录，与模型上下文相互独立。"""

    role: TranscriptRole
    content: str = ""
    thinking: str = ""
    state: TranscriptState = "complete"
    tool_name: str | None = None
    call_id: str | None = None


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


class ToolMessage(Vertical):
    """一条有界的工具调用和结果摘要。"""

    DEFAULT_CSS = """
    ToolMessage {
        height: auto;
        margin: 1 2 0 2;
        padding: 0 1;
        border-left: thick $warning;
    }
    ToolMessage .tool-label {
        height: 1;
        color: $warning;
        text-style: bold;
    }
    ToolMessage .tool-content {
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, entry: TranscriptEntry) -> None:
        super().__init__(classes=f"tool-message {entry.state}")
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Static(f"工具  {self.entry.tool_name or 'unknown'}", classes="tool-label")
        yield Static(self.entry.content, classes="tool-content")

    def refresh_entry(self) -> None:
        self.set_classes(f"tool-message {self.entry.state}")
        self.query_one(".tool-content", Static).update(self.entry.content)


class CommandApprovalScreen(ModalScreen[bool]):
    """逐次确认完整 Shell 命令。"""

    BINDINGS = [
        Binding("y", "approve", priority=True, show=False),
        Binding("enter", "approve", priority=True, show=False),
        Binding("n", "reject", priority=True, show=False),
        Binding("escape", "reject", priority=True, show=False),
    ]

    DEFAULT_CSS = """
    CommandApprovalScreen {
        align: center middle;
        background: $background 60%;
    }
    CommandApprovalScreen > Vertical {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        border: round $warning;
        background: $panel;
    }
    #approval-title { height: 1; text-style: bold; color: $warning; }
    #approval-command { height: auto; max-height: 12; overflow-y: auto; margin-top: 1; }
    #approval-details { height: auto; color: $text-muted; margin-top: 1; }
    #approval-buttons { height: 3; align-horizontal: right; margin-top: 1; }
    #approval-buttons Button { margin-left: 1; }
    """

    def __init__(self, request: CommandApprovalRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("允许执行命令？", id="approval-title")
            yield Static(self.request.command, id="approval-command", markup=False)
            yield Static(
                f"工作目录：{self.request.cwd}\n超时：{self.request.timeout_seconds:g} 秒",
                id="approval-details",
                markup=False,
            )
            with Horizontal(id="approval-buttons"):
                yield Button("拒绝 (N/Esc)", id="reject-command")
                yield Button("执行 (Y/Enter)", variant="warning", id="approve-command")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve-command")


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

    async def append_message(
        self, widget: UserMessage | AssistantMessage | ToolMessage | StatusMessage
    ) -> None:
        follow = self.is_vertical_scroll_end
        await self.mount(widget)
        if follow:
            self._follow_after_layout()

    async def insert_message_before(
        self,
        widget: ToolMessage,
        before: AssistantMessage,
    ) -> None:
        """把工具记录放在本轮最终助手答复之前。"""

        follow = self.is_vertical_scroll_end
        await self.mount(widget, before=before)
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
        self.tool_messages: dict[str, ToolMessage] = {}
        self.approval_screen: CommandApprovalScreen | None = None
        self.mode = AgentMode.NORMAL
        self.iteration = 0
        self.usage_text = "Token ?"

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
        self.transcript.append(user_entry)

        conversation = self.query_one(ConversationView)
        await conversation.append_message(UserMessage(user_entry))

        self.is_generating = True
        self.current_entry = None
        self.current_message = None
        self.tool_messages = {}
        self.query_one("#composer-status", Static).update(self._status_text("正在生成"))
        self.reply_worker = self.run_worker(
            self._consume_reply(user_input),
            name="reply",
            group="reply",
            exclusive=True,
            exit_on_error=False,
        )

    async def _consume_reply(self, user_input: str) -> None:
        conversation = self.query_one(ConversationView)
        iteration_messages: dict[int, tuple[TranscriptEntry, AssistantMessage]] = {}

        async def ensure_message(iteration: int) -> tuple[TranscriptEntry, AssistantMessage]:
            existing = iteration_messages.get(iteration)
            if existing is not None:
                return existing
            entry = TranscriptEntry("assistant", state="streaming")
            message = AssistantMessage(entry)
            self.transcript.append(entry)
            await conversation.append_message(message)
            iteration_messages[iteration] = (entry, message)
            self.current_entry = entry
            self.current_message = message
            return entry, message

        try:
            async for event in self.session.stream_reply(user_input):
                if event.kind == AgentEventKind.MODE_CHANGED:
                    self.mode = event.mode
                    self.query_one("#composer-status", Static).update(
                        self._status_text("模式已切换")
                    )
                elif event.kind == AgentEventKind.ITERATION_STARTED:
                    self.iteration = event.iteration
                    self.query_one("#composer-status", Static).update(self._status_text("请求模型"))
                elif event.kind == AgentEventKind.THINKING_DELTA:
                    entry, message = await ensure_message(event.iteration)
                    entry.thinking += event.delta
                    await conversation.refresh_message(message)
                elif event.kind == AgentEventKind.TEXT_DELTA:
                    entry, message = await ensure_message(event.iteration)
                    entry.content += event.delta
                    await conversation.refresh_message(message)
                elif event.kind == AgentEventKind.TOOL_CALL and event.tool_call is not None:
                    tool_entry = TranscriptEntry(
                        "tool",
                        content=self._tool_call_summary(event.tool_call),
                        state="pending",
                        tool_name=event.tool_call.name,
                        call_id=event.tool_call.id,
                    )
                    self.transcript.append(tool_entry)
                    tool_message = ToolMessage(tool_entry)
                    self.tool_messages[event.tool_call.id] = tool_message
                    await conversation.append_message(tool_message)
                elif event.kind == AgentEventKind.TOOL_RESULT and event.tool_result is not None:
                    tool_message = self.tool_messages.get(event.tool_result.call_id)
                    if tool_message is not None:
                        result = event.tool_result
                        tool_message.entry.content = result.summary()
                        if result.success:
                            tool_message.entry.state = "complete"
                        elif result.error_code == ToolErrorCode.USER_REJECTED:
                            tool_message.entry.state = "rejected"
                        elif result.error_code == ToolErrorCode.CANCELLED:
                            tool_message.entry.state = "cancelled"
                        else:
                            tool_message.entry.state = "error"
                        tool_message.refresh_entry()
                elif event.kind == AgentEventKind.TOKEN_USAGE and event.usage is not None:
                    total = event.usage.cumulative.total_tokens
                    self.usage_text = f"Token {total}" if total is not None else "Token ?"
                    self.query_one("#composer-status", Static).update(self._status_text("正在生成"))
                elif event.kind == AgentEventKind.PROGRESS and event.progress is not None:
                    progress = event.progress
                    if progress.phase == "executing_tools":
                        detail = f"工具 {progress.completed_tools}/{progress.total_tools}"
                    elif progress.phase == "checkpoint_committed":
                        detail = "已保存检查点"
                        current = iteration_messages.get(progress.iteration)
                        if current is not None:
                            current[0].state = "complete"
                            await conversation.refresh_message(current[1])
                    else:
                        detail = "请求模型"
                    self.query_one("#composer-status", Static).update(self._status_text(detail))
                elif event.kind == AgentEventKind.STOPPED:
                    await self._apply_stop(event.stop_reason, event.delta, iteration_messages)
        except asyncio.CancelledError:
            self.session.cancel_current()
            raise
        except Exception:
            entry, message = await ensure_message(self.iteration)
            entry.state = "error"
            entry.thinking = ""
            entry.content = "Agent 运行发生内部错误。"
            await conversation.refresh_message(message)
        finally:
            self.is_generating = False
            self.current_entry = None
            self.current_message = None
            self.reply_worker = None
            self.query_one("#composer-status", Static).update(self._status_text("就绪"))
            self.query_one(ComposerTextArea).focus()

    def _status_text(self, detail: str) -> str:
        mode = "Plan" if self.mode == AgentMode.PLAN else "Normal"
        iteration = f" · {self.iteration}/10" if self.iteration else ""
        return f"{mode}{iteration} · {self.usage_text} · {detail}"

    async def _apply_stop(
        self,
        reason: AgentStopReason | None,
        detail: str,
        messages: dict[int, tuple[TranscriptEntry, AssistantMessage]],
    ) -> None:
        conversation = self.query_one(ConversationView)
        if reason == AgentStopReason.COMPLETED:
            for entry, message in messages.values():
                entry.state = "complete"
                await conversation.refresh_message(message)
            return

        labels = {
            AgentStopReason.ITERATION_LIMIT: "已达到 10 次迭代上限。",
            AgentStopReason.UNKNOWN_TOOL_LIMIT: "连续请求未知工具，Agent 已停止。",
            AgentStopReason.CANCELLED: "已取消当前回复。",
            AgentStopReason.PROVIDER_ERROR: f"请求失败：{detail or '模型服务请求失败。'}",
            AgentStopReason.INVALID_STREAM: detail or "模型返回了无效的流式响应。",
            AgentStopReason.NO_PLAN: detail or "当前没有已完成的计划可执行。",
            AgentStopReason.INVALID_COMMAND: detail or "命令格式无效。",
        }
        text = labels.get(reason, detail or "Agent 已停止。")
        state: TranscriptState = "cancelled" if reason == AgentStopReason.CANCELLED else "error"
        for entry, message in messages.values():
            if entry.state == "streaming":
                entry.state = state
                if reason == AgentStopReason.CANCELLED:
                    entry.content = text
                elif not entry.content:
                    entry.content = text
                if state == "cancelled":
                    entry.thinking = ""
                await conversation.refresh_message(message)
        for tool_message in self.tool_messages.values():
            if tool_message.entry.state in {"pending", "approved"}:
                tool_message.entry.state = state
                tool_message.entry.content = text
                tool_message.refresh_entry()
        if not messages or reason in {
            AgentStopReason.ITERATION_LIMIT,
            AgentStopReason.UNKNOWN_TOOL_LIMIT,
            AgentStopReason.PROVIDER_ERROR,
            AgentStopReason.INVALID_STREAM,
            AgentStopReason.NO_PLAN,
            AgentStopReason.INVALID_COMMAND,
        }:
            status_entry = TranscriptEntry("status", text, state=state)
            self.transcript.append(status_entry)
            await conversation.append_message(StatusMessage(status_entry))

    @staticmethod
    def _tool_call_summary(call: ToolCall) -> str:
        try:
            arguments = json.loads(call.arguments_json)
        except json.JSONDecodeError:
            return "等待执行。"
        for key in ("command", "path", "query", "pattern"):
            value = arguments.get(key) if isinstance(arguments, dict) else None
            if isinstance(value, str):
                return value[:500]
        return "等待执行。"

    async def request_command_approval(self, request: CommandApprovalRequest) -> bool:
        """显示一次性命令确认框并恢复输入焦点。"""

        screen = CommandApprovalScreen(request)
        self.approval_screen = screen
        self.query_one("#composer-status", Static).update(self._status_text("等待命令确认"))
        try:
            approved = await self.push_screen_wait(screen)
            for tool_message in reversed(tuple(self.tool_messages.values())):
                if (
                    tool_message.entry.tool_name == "execute_command"
                    and tool_message.entry.state == "pending"
                ):
                    tool_message.entry.state = "approved" if approved else "rejected"
                    tool_message.entry.content = "已批准，正在执行。" if approved else "已拒绝。"
                    tool_message.refresh_entry()
                    break
            return approved
        finally:
            self.approval_screen = None
            self.query_one("#composer-status", Static).update(self._status_text("正在生成"))
            self.query_one(ComposerTextArea).focus()

    def action_cancel_or_clear(self) -> None:
        if self.is_generating and self.reply_worker is not None:
            if self.approval_screen is not None and self.approval_screen.is_mounted:
                self.approval_screen.dismiss(False)
            self.session.cancel_current()
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
        elif entry.role == "tool":
            console.print(f"[bold yellow]工具  {entry.tool_name or 'unknown'}[/bold yellow]")
            console.print(f"{entry.state} · {entry.content}", style="yellow")
        else:
            console.print(entry.content, style="yellow")
