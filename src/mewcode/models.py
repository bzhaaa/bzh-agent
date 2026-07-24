"""供应商无关的对话领域模型。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """一条完整的对话消息。"""

    role: Literal["user", "assistant"]
    content: str


class StreamEventKind(StrEnum):
    """TUI 可以消费的流事件。"""

    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """供应商统一流事件。"""

    kind: StreamEventKind
    delta: str = ""
