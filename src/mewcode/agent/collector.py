"""Provider 流的实时转发与完整响应收集。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from mewcode.agent.control import AgentRunCancelled, AgentRunControl, wait_with_control
from mewcode.agent.events import AgentEvent, AgentEventKind, AgentMode
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ProviderEvent, ProviderEventKind, TokenUsage
from mewcode.tools.base import ToolCall


@dataclass(frozen=True, slots=True)
class CollectedResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage


class StreamCollector:
    def __init__(self, *, iteration: int, mode: AgentMode, control: AgentRunControl) -> None:
        self.iteration = iteration
        self.mode = mode
        self.control = control
        self._response: CollectedResponse | None = None
        self._usage: TokenUsage | None = None

    @property
    def response(self) -> CollectedResponse:
        if self._response is None:
            raise RuntimeError("Provider 流尚未完整结束。")
        return self._response

    @property
    def usage(self) -> TokenUsage:
        """返回当前已观察到的用量，供失败路径生成事件。"""

        return self._usage or TokenUsage(None, None)

    @staticmethod
    def _invalid() -> ProviderError:
        return ProviderError(ProviderErrorKind.INVALID_STREAM)

    async def consume(self, source: AsyncIterator[ProviderEvent]) -> AsyncIterator[AgentEvent]:
        if self._response is not None:
            raise RuntimeError("同一个收集器不能重复使用。")
        iterator = source.__aiter__()
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        call_ids: set[str] = set()
        saw_done = False
        try:
            while True:
                next_event = asyncio.create_task(anext(iterator))
                try:
                    event = await wait_with_control(next_event, self.control)
                except StopAsyncIteration:
                    break
                if saw_done:
                    raise self._invalid()
                if event.kind == ProviderEventKind.THINKING_DELTA:
                    if not event.delta or event.tool_call is not None or event.usage is not None:
                        raise self._invalid()
                    yield AgentEvent(
                        AgentEventKind.THINKING_DELTA,
                        self.iteration,
                        self.mode,
                        delta=event.delta,
                    )
                elif event.kind == ProviderEventKind.TEXT_DELTA:
                    if not event.delta or event.tool_call is not None or event.usage is not None:
                        raise self._invalid()
                    text_parts.append(event.delta)
                    yield AgentEvent(
                        AgentEventKind.TEXT_DELTA,
                        self.iteration,
                        self.mode,
                        delta=event.delta,
                    )
                elif event.kind == ProviderEventKind.TOOL_CALL:
                    if event.tool_call is None or event.delta or event.usage is not None:
                        raise self._invalid()
                    call = event.tool_call
                    try:
                        arguments = json.loads(call.arguments_json)
                    except (json.JSONDecodeError, TypeError) as error:
                        raise self._invalid() from error
                    if (
                        not call.id
                        or not call.name
                        or call.id in call_ids
                        or not isinstance(arguments, dict)
                    ):
                        raise self._invalid()
                    call_ids.add(call.id)
                    calls.append(event.tool_call)
                    yield AgentEvent(
                        AgentEventKind.TOOL_CALL,
                        self.iteration,
                        self.mode,
                        tool_call=event.tool_call,
                    )
                elif event.kind == ProviderEventKind.TOKEN_USAGE:
                    if (
                        event.usage is None
                        or event.delta
                        or event.tool_call is not None
                        or self._usage is not None
                    ):
                        raise self._invalid()
                    if any(
                        value is not None and value < 0
                        for value in (event.usage.input_tokens, event.usage.output_tokens)
                    ):
                        raise self._invalid()
                    self._usage = event.usage
                elif event.kind == ProviderEventKind.DONE:
                    if event.delta or event.tool_call is not None or event.usage is not None:
                        raise self._invalid()
                    saw_done = True
                else:
                    raise self._invalid()
        except AgentRunCancelled:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
            raise
        except asyncio.CancelledError:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
            raise
        if not saw_done:
            raise self._invalid()
        self._response = CollectedResponse(
            "".join(text_parts),
            tuple(calls),
            self.usage,
        )
