"""对话会话、工具编排和历史事务。"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    AssistantMessage,
    ChatMessage,
    StreamEvent,
    StreamEventKind,
    ToolResultMessage,
    UserMessage,
)
from mewcode.providers import LLMProvider
from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    create_default_registry,
)


class ChatSession:
    """每回合最多执行一个工具，并只提交完整轮次。"""

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
        context: ToolContext | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry or create_default_registry()
        self.executor = executor or ToolExecutor(self.registry)
        self.context = context or ToolContext(Path.cwd().resolve())
        self._history: list[ChatMessage] = []

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    def _provider_stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        """兼容尚未声明 tools 参数的测试 Provider。"""

        parameters = inspect.signature(self.provider.stream).parameters
        if len(parameters) >= 2:
            return self.provider.stream(messages, self.registry.definitions())
        return self.provider.stream(messages)

    @staticmethod
    def _multiple_result(call: ToolCall) -> ToolResult:
        return ToolResult(
            call.id,
            call.name,
            False,
            {},
            error_code=ToolErrorCode.MULTIPLE_TOOLS,
            error_message="每个用户回合只允许一个工具；同批调用均未执行。",
        )

    async def stream_reply(self, user_input: str) -> AsyncIterator[StreamEvent]:
        """执行纯文本或单工具两阶段回合，最终成功后原子提交历史。"""

        pending_user = UserMessage(user_input)
        first_candidate = (*self._history, pending_user)
        first_text: list[str] = []
        first_calls: list[ToolCall] = []
        first_done = False

        async for event in self._provider_stream(first_candidate):
            if event.kind == StreamEventKind.TEXT_DELTA:
                first_text.append(event.delta)
                yield event
            elif event.kind == StreamEventKind.THINKING_DELTA:
                yield event
            elif event.kind == StreamEventKind.TOOL_CALL:
                if event.tool_call is None:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                first_calls.append(event.tool_call)
                yield event
            elif event.kind == StreamEventKind.DONE:
                if first_done:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                first_done = True
            else:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        if not first_done:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)

        first_content = "".join(first_text)
        if not first_calls:
            if not first_content:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
            self._history.extend((pending_user, AssistantMessage(first_content)))
            yield StreamEvent(StreamEventKind.DONE)
            return

        if len(first_calls) > 1:
            results = [self._multiple_result(call) for call in first_calls]
        else:
            results = [await self.executor.execute(first_calls[0], self.context)]
        for result in results:
            yield StreamEvent(StreamEventKind.TOOL_RESULT, tool_result=result)

        tool_messages = tuple(ToolResultMessage(result) for result in results)
        pending_history: tuple[ChatMessage, ...] = (
            pending_user,
            AssistantMessage(first_content, tuple(first_calls)),
            *tool_messages,
        )
        second_candidate = (*self._history, *pending_history)
        second_text: list[str] = []
        second_calls: list[ToolCall] = []
        second_done = False
        async for event in self._provider_stream(second_candidate):
            if event.kind == StreamEventKind.TEXT_DELTA:
                second_text.append(event.delta)
                yield event
            elif event.kind == StreamEventKind.THINKING_DELTA:
                yield event
            elif event.kind == StreamEventKind.TOOL_CALL:
                if event.tool_call is None:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                second_calls.append(event.tool_call)
                yield event
            elif event.kind == StreamEventKind.DONE:
                if second_done:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                second_done = True
            else:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        if not second_done:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        if second_calls:
            yield StreamEvent(
                StreamEventKind.LIMIT_REACHED,
                delta="本阶段不支持连续工具调用；该工具未执行。",
            )
            return
        final_content = "".join(second_text)
        if not final_content:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        self._history.extend((*pending_history, AssistantMessage(final_content)))
        yield StreamEvent(StreamEventKind.DONE)
