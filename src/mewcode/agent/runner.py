"""供应商无关的 ReAct Agent Loop。"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from mewcode.agent.collector import StreamCollector
from mewcode.agent.control import AgentRunCancelled, AgentRunControl
from mewcode.agent.events import (
    AgentEvent,
    AgentEventKind,
    AgentMode,
    AgentProgress,
    AgentStopReason,
    UsageSnapshot,
)
from mewcode.agent.scheduler import ToolScheduler
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    AssistantMessage,
    ChatMessage,
    TokenUsage,
    ToolResultMessage,
    UserMessage,
)
from mewcode.providers.base import LLMProvider
from mewcode.tools.base import ToolContext
from mewcode.tools.errors import ToolErrorCode

DEFAULT_MAX_ITERATIONS = 10


class HistorySink(Protocol):
    async def commit(self, messages: Sequence[ChatMessage]) -> None: ...


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    history: tuple[ChatMessage, ...]
    user_message: UserMessage
    mode: AgentMode
    control: AgentRunControl
    history_sink: HistorySink
    max_iterations: int = DEFAULT_MAX_ITERATIONS


class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        normal_scheduler: ToolScheduler,
        plan_scheduler: ToolScheduler,
        context: ToolContext,
    ) -> None:
        self.provider = provider
        self.normal_scheduler = normal_scheduler
        self.plan_scheduler = plan_scheduler
        self.context = context

    def _provider_stream(self, messages: Sequence[ChatMessage], scheduler: ToolScheduler):
        parameters = inspect.signature(self.provider.stream).parameters
        if len(parameters) >= 2:
            return self.provider.stream(messages, scheduler.registry.definitions())
        return self.provider.stream(messages)

    @staticmethod
    def _event(
        kind: AgentEventKind,
        iteration: int,
        mode: AgentMode,
        **kwargs: object,
    ) -> AgentEvent:
        return AgentEvent(kind, iteration, mode, **kwargs)  # type: ignore[arg-type]

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        if request.max_iterations < 1:
            raise ValueError("迭代上限必须大于零。")
        scheduler = self.plan_scheduler if request.mode == AgentMode.PLAN else self.normal_scheduler
        history = list(request.history)
        user_pending = True
        unknown_streak = 0
        cumulative = TokenUsage(0, 0)

        for iteration in range(1, request.max_iterations + 1):
            if request.control.is_cancelled():
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration - 1,
                    request.mode,
                    stop_reason=AgentStopReason.CANCELLED,
                )
                return
            yield self._event(AgentEventKind.ITERATION_STARTED, iteration, request.mode)
            yield self._event(
                AgentEventKind.PROGRESS,
                iteration,
                request.mode,
                progress=AgentProgress("requesting_model", iteration),
            )
            candidate: tuple[ChatMessage, ...] = (
                (*history, request.user_message) if user_pending else tuple(history)
            )
            collector = StreamCollector(
                iteration=iteration,
                mode=request.mode,
                control=request.control,
            )
            try:
                async for event in collector.consume(self._provider_stream(candidate, scheduler)):
                    yield event
                response = collector.response
            except AgentRunCancelled:
                unknown = TokenUsage(None, None)
                cumulative = cumulative.accumulate(unknown)
                yield self._event(
                    AgentEventKind.TOKEN_USAGE,
                    iteration,
                    request.mode,
                    usage=UsageSnapshot(unknown, cumulative),
                )
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    stop_reason=AgentStopReason.CANCELLED,
                )
                return
            except ProviderError as error:
                request_usage = collector.usage
                cumulative = cumulative.accumulate(request_usage)
                yield self._event(
                    AgentEventKind.TOKEN_USAGE,
                    iteration,
                    request.mode,
                    usage=UsageSnapshot(request_usage, cumulative),
                )
                reason = (
                    AgentStopReason.INVALID_STREAM
                    if error.kind == ProviderErrorKind.INVALID_STREAM
                    else AgentStopReason.PROVIDER_ERROR
                )
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    delta=str(error),
                    stop_reason=reason,
                )
                return

            cumulative = cumulative.accumulate(response.usage)
            yield self._event(
                AgentEventKind.TOKEN_USAGE,
                iteration,
                request.mode,
                usage=UsageSnapshot(response.usage, cumulative),
            )
            if not response.tool_calls:
                if not response.content:
                    yield self._event(
                        AgentEventKind.STOPPED,
                        iteration,
                        request.mode,
                        stop_reason=AgentStopReason.INVALID_STREAM,
                    )
                    return
                messages: list[ChatMessage] = []
                if user_pending:
                    messages.append(request.user_message)
                messages.append(AssistantMessage(response.content))
                await request.history_sink.commit(messages)
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    stop_reason=AgentStopReason.COMPLETED,
                )
                return

            yield self._event(
                AgentEventKind.PROGRESS,
                iteration,
                request.mode,
                progress=AgentProgress(
                    "executing_tools",
                    iteration,
                    total_tools=len(response.tool_calls),
                ),
            )
            results = []
            completed = 0
            async for segment in scheduler.execute(
                response.tool_calls, self.context, request.control
            ):
                for result in segment.results:
                    results.append(result)
                    completed += 1
                    yield self._event(
                        AgentEventKind.TOOL_RESULT,
                        iteration,
                        request.mode,
                        tool_result=result,
                    )
                yield self._event(
                    AgentEventKind.PROGRESS,
                    iteration,
                    request.mode,
                    progress=AgentProgress(
                        "executing_tools",
                        iteration,
                        completed_tools=completed,
                        total_tools=len(response.tool_calls),
                    ),
                )

            checkpoint: list[ChatMessage] = []
            if user_pending:
                checkpoint.append(request.user_message)
            checkpoint.append(AssistantMessage(response.content, response.tool_calls))
            checkpoint.extend(ToolResultMessage(result) for result in results)
            await request.history_sink.commit(checkpoint)
            history.extend(checkpoint)
            user_pending = False
            yield self._event(
                AgentEventKind.PROGRESS,
                iteration,
                request.mode,
                progress=AgentProgress(
                    "checkpoint_committed",
                    iteration,
                    completed_tools=len(results),
                    total_tools=len(response.tool_calls),
                ),
            )

            if request.control.is_cancelled():
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    stop_reason=AgentStopReason.CANCELLED,
                )
                return
            pure_unknown = all(
                result.error_code == ToolErrorCode.UNKNOWN_TOOL for result in results
            )
            unknown_streak = unknown_streak + 1 if pure_unknown else 0
            if unknown_streak >= 2:
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    stop_reason=AgentStopReason.UNKNOWN_TOOL_LIMIT,
                )
                return
            if iteration == request.max_iterations:
                yield self._event(
                    AgentEventKind.STOPPED,
                    iteration,
                    request.mode,
                    stop_reason=AgentStopReason.ITERATION_LIMIT,
                )
                return
