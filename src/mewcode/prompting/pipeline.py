"""为单次 Provider 请求组装结构化提示信封。"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mewcode.models import AgentMode, ChatMessage
from mewcode.prompting.builder import StablePromptBuilder, SupplementBuilder
from mewcode.prompting.environment import EnvironmentCollector
from mewcode.prompting.models import PromptEnvelope, PromptOptions, StructuredPrompt
from mewcode.prompting.reminders import ReminderScheduler
from mewcode.tools.base import ToolDefinition


class PromptPipeline:
    """组合稳定提示、动态环境、模式提醒和请求数据。"""

    def __init__(
        self,
        stable_builder: StablePromptBuilder | None = None,
        supplement_builder: SupplementBuilder | None = None,
        environment_collector: EnvironmentCollector | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
    ) -> None:
        self.stable_builder = stable_builder or StablePromptBuilder()
        self.supplement_builder = supplement_builder or SupplementBuilder()
        self.environment_collector = environment_collector or EnvironmentCollector()
        self.reminder_scheduler = reminder_scheduler or ReminderScheduler()

    def validate_options(self, options: PromptOptions) -> None:
        self.supplement_builder.validate_options(options)

    async def build(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition],
        project_root: Path,
        mode: AgentMode,
        iteration: int,
        options: PromptOptions,
    ) -> PromptEnvelope:
        snapshot = await self.environment_collector.collect(project_root, mode)
        reminder = self.reminder_scheduler.build(mode, iteration)
        supplement = self.supplement_builder.build(snapshot, reminder, options)
        return PromptEnvelope(
            StructuredPrompt(self.stable_builder.build(), (supplement,)),
            tuple(messages),
            tuple(tools),
        )
