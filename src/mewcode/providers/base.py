"""Provider 公共接口和常量。"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from mewcode.models import ChatMessage, ProviderEvent
from mewcode.tools.base import ToolDefinition

DEFAULT_MAX_TOKENS = 4096
THINKING_MAX_TOKENS = 8192
THINKING_BUDGET_TOKENS = 4096


@runtime_checkable
class LLMProvider(Protocol):
    """所有模型供应商必须实现的接口。"""

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AsyncIterator[ProviderEvent]:
        """返回统一的异步流事件。"""
        ...
