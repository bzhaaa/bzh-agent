"""供应商无关的对话领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mewcode.tools.base import ToolCall, ToolResult


class _ChatMessageMeta(type):
    def __call__(cls, *args: object, **kwargs: object) -> ChatMessage:
        if cls is ChatMessage:
            role = str(args[0]) if args else str(kwargs.get("role", ""))
            content = str(args[1]) if len(args) > 1 else str(kwargs.get("content", ""))
            if role == "user":
                return UserMessage(content)
            if role == "assistant":
                return AssistantMessage(content)
            raise ValueError(f"不支持的消息角色：{role}")
        return super().__call__(*args, **kwargs)


class ChatMessage(metaclass=_ChatMessageMeta):
    """对话消息基类，并兼容旧的 ``ChatMessage(role, content)`` 构造方式。"""


@dataclass(frozen=True, slots=True)
class UserMessage(ChatMessage):
    """用户消息。"""

    content: str

    @property
    def role(self) -> str:
        return "user"


@dataclass(frozen=True, slots=True)
class AssistantMessage(ChatMessage):
    """助手文字和同批工具调用。"""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()

    @property
    def role(self) -> str:
        return "assistant"


@dataclass(frozen=True, slots=True)
class ToolResultMessage(ChatMessage):
    """一个工具调用对应的结构化结果。"""

    result: ToolResult

    @property
    def role(self) -> str:
        return "tool"


class StreamEventKind(StrEnum):
    """TUI 可以消费的流事件。"""

    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    LIMIT_REACHED = "limit_reached"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """供应商统一流事件。"""

    kind: StreamEventKind
    delta: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
