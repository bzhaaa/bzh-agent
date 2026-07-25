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
            )
        self.context = self.runner.context
        self.max_iterations = max_iterations
        self._history: list[ChatMessage] = []
        self._mode = AgentMode.NORMAL
        self._plan_ready = False
        self._current: AgentRunControl | None = None

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @property
    def plan_ready(self) -> bool:
        return self._plan_ready

    async def commit(self, messages: Sequence[ChatMessage]) -> None:
        self._history.extend(messages)

    def cancel_current(self) -> None:
        if self._current is not None:
            self._current.cancel()

    @staticmethod
    def _plan_instruction(task: str) -> str:
        return (
            "你现在处于只读 Plan Mode。只能调查项目并形成可执行计划，"
            "不得修改文件或执行命令。\n\n用户任务：\n" + task
        )

    @staticmethod
    def _plan_followup(message: str) -> str:
        return (
            "继续在只读 Plan Mode 中调查并更新计划。不得修改文件或执行命令。"
            "\n\n用户补充：\n" + message
        )

    @staticmethod
    def _do_instruction() -> str:
        return (
            "退出 Plan Mode。请根据当前对话中已经完成的任务调查与计划开始执行，"
            "自主使用可用工具，直到任务完成。"
        )

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
            model_input = self._plan_instruction(task)
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
            model_input = self._do_instruction()
            mode_event = AgentEvent(AgentEventKind.MODE_CHANGED, mode=self._mode)
        elif self._mode == AgentMode.PLAN:
            model_input = self._plan_followup(user_input)
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
