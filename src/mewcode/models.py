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


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """一次模型请求的归一化 Token 用量。"""

    input_tokens: int | None
    output_tokens: int | None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def accumulate(self, other: TokenUsage) -> TokenUsage:
        """累计用量，任一未知值会向后传播。"""

        input_tokens = (
            None
            if self.input_tokens is None or other.input_tokens is None
            else self.input_tokens + other.input_tokens
        )
        output_tokens = (
            None
            if self.output_tokens is None or other.output_tokens is None
            else self.output_tokens + other.output_tokens
        )
        return TokenUsage(input_tokens, output_tokens)


class ProviderEventKind(StrEnum):
    """Provider 与流收集器之间的统一事件。"""

    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOKEN_USAGE = "token_usage"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """供应商无关的底层流事件。"""

    kind: ProviderEventKind
    delta: str = ""
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
