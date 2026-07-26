"""对话历史、Plan Mode 和 Agent Run 外观层。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from mewcode.agent import (
    AgentEvent,
    AgentEventKind,
    AgentMode,
    AgentRunControl,
    AgentStopReason,
)
from mewcode.agent.runner import DEFAULT_MAX_ITERATIONS, AgentRunner, AgentRunRequest
from mewcode.agent.scheduler import ToolScheduler
from mewcode.models import ChatMessage, UserMessage
from mewcode.prompting import PromptOptions, PromptPipeline
from mewcode.providers import LLMProvider
from mewcode.tools import ToolContext, ToolExecutor, ToolRegistry, create_default_registry

READ_ONLY_TOOLS = ("read_file", "find_files", "search_code")


class ChatSession:
    """保存会话状态，并把每条输入转换为一次独立 Agent Run。"""

    def __init__(
        self,
        runner: AgentRunner | LLMProvider,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
        context: ToolContext | None = None,
        *,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        prompt_options: PromptOptions | None = None,
    ) -> None:
        if isinstance(runner, AgentRunner):
            self.runner = runner
        else:
            all_tools = registry or create_default_registry()
            all_executor = executor or ToolExecutor(all_tools)
            run_context = context or ToolContext(Path.cwd().resolve())
            readonly = all_tools.subset(READ_ONLY_TOOLS)
            self.runner = AgentRunner(
                runner,
                ToolScheduler(all_tools, all_executor),
                ToolScheduler(readonly, ToolExecutor(readonly)),
                run_context,
                PromptPipeline(),
            )
        self.context = self.runner.context
        self.max_iterations = max_iterations
        self._history: list[ChatMessage] = []
        self._mode = AgentMode.NORMAL
        self._plan_ready = False
        self._current: AgentRunControl | None = None
        initial_options = prompt_options or PromptOptions()
        self._prompt_options = initial_options
        self.runner.prompt_pipeline.validate_options(initial_options)

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @property
    def plan_ready(self) -> bool:
        return self._plan_ready

    @property
    def prompt_options(self) -> PromptOptions:
        return self._prompt_options

    def set_prompt_options(self, options: PromptOptions) -> None:
        """在没有活动 Run 时原子替换动态提示选项。"""

        if self._current is not None:
            raise RuntimeError("Agent Run 进行中，不能更新提示选项。")
        self.runner.prompt_pipeline.validate_options(options)
        self._prompt_options = options

    async def commit(self, messages: Sequence[ChatMessage]) -> None:
        self._history.extend(messages)

    def cancel_current(self) -> None:
        if self._current is not None:
            self._current.cancel()

    async def stream_reply(self, user_input: str) -> AsyncIterator[AgentEvent]:
        if self._current is not None:
            raise RuntimeError("当前已有 Agent Run 正在执行。")

        stripped = user_input.strip()
        mode_event: AgentEvent | None = None
        if stripped == "/plan":
            yield AgentEvent(
                AgentEventKind.STOPPED,
                mode=self._mode,
                delta="/plan 后需要提供任务。",
                stop_reason=AgentStopReason.INVALID_COMMAND,
            )
            return
        if stripped.startswith("/plan "):
            task = stripped[6:].strip()
            if not task:
                yield AgentEvent(
                    AgentEventKind.STOPPED,
                    mode=self._mode,
                    delta="/plan 后需要提供任务。",
                    stop_reason=AgentStopReason.INVALID_COMMAND,
                )
                return
            self._mode = AgentMode.PLAN
            self._plan_ready = False
            model_input = task
            mode_event = AgentEvent(AgentEventKind.MODE_CHANGED, mode=self._mode)
        elif stripped == "/do":
            if not self._plan_ready:
                yield AgentEvent(
                    AgentEventKind.STOPPED,
                    mode=self._mode,
                    delta="当前没有已完成的计划可执行。",
                    stop_reason=AgentStopReason.NO_PLAN,
                )
                return
            self._plan_ready = False
            self._mode = AgentMode.NORMAL
            model_input = "/do"
            mode_event = AgentEvent(AgentEventKind.MODE_CHANGED, mode=self._mode)
        elif self._mode == AgentMode.PLAN:
            model_input = user_input
            self._plan_ready = False
        else:
            model_input = user_input

        if mode_event is not None:
            yield mode_event
        control = AgentRunControl()
        self._current = control
        completed = False
        try:
            request = AgentRunRequest(
                history=self.history,
                user_message=UserMessage(model_input),
                mode=self._mode,
                control=control,
                history_sink=self,
                prompt_options=self._prompt_options,
                max_iterations=self.max_iterations,
            )
            async for event in self.runner.run(request):
                if (
                    event.kind == AgentEventKind.STOPPED
                    and event.stop_reason == AgentStopReason.COMPLETED
                ):
                    completed = True
                yield event
        finally:
            if self._current is control:
                self._current = None
        if self._mode == AgentMode.PLAN and completed:
            self._plan_ready = True
