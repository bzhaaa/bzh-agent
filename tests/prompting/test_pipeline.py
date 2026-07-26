"""Prompt Pipeline 与提醒频率测试。"""

from pathlib import Path

import pytest

from mewcode.agent import AgentMode
from mewcode.models import UserMessage
from mewcode.prompting import (
    EnvironmentSnapshot,
    PromptOptions,
    PromptPipeline,
    ReminderDetail,
    ReminderScheduler,
)
from mewcode.tools import create_default_registry


class FakeEnvironmentCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, AgentMode]] = []

    async def collect(self, project_root: Path, mode: AgentMode) -> EnvironmentSnapshot:
        self.calls.append((project_root, mode))
        return EnvironmentSnapshot(
            project_root="~/fixture",
            platform="TestOS",
            shell="zsh",
            current_date=f"2026-07-{25 + len(self.calls):02d}",
            timezone="CST",
            git_branch="main",
            git_dirty=len(self.calls) % 2 == 0,
            mode=mode,
        )


def test_reminder_schedule_is_full_on_first_and_sixth_request() -> None:
    scheduler = ReminderScheduler()
    assert [scheduler.detail_for(index) for index in range(1, 11)] == [
        ReminderDetail.FULL,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
        ReminderDetail.FULL,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
        ReminderDetail.COMPACT,
    ]
    assert scheduler.detail_for(1) == ReminderDetail.FULL
    with pytest.raises(ValueError):
        scheduler.detail_for(0)


@pytest.mark.asyncio
async def test_pipeline_freezes_envelope_and_keeps_stable_prefix() -> None:
    environment = FakeEnvironmentCollector()
    pipeline = PromptPipeline(environment_collector=environment)  # type: ignore[arg-type]
    messages = [UserMessage("任务")]
    tools = create_default_registry().definitions()
    first = await pipeline.build(
        messages=messages,
        tools=tools,
        project_root=Path("/fixture"),
        mode=AgentMode.NORMAL,
        iteration=1,
        options=PromptOptions(
            custom_instructions="自定义",
            active_skills=("技能一", "技能二"),
            long_term_memory="记忆",
        ),
    )
    messages.append(UserMessage("不应进入已构建信封"))
    second = await pipeline.build(
        messages=(UserMessage("另一任务"),),
        tools=tools,
        project_root=Path("/fixture"),
        mode=AgentMode.NORMAL,
        iteration=2,
        options=PromptOptions(),
    )
    assert first.prompt.stable_system == second.prompt.stable_system
    assert first.prompt.supplements != second.prompt.supplements
    assert first.messages == (UserMessage("任务"),)
    assert first.tools == tools
    supplement = first.prompt.supplements[0]
    assert supplement.index("<environment>") < supplement.index("<custom-instructions>")
    assert supplement.index("<custom-instructions>") < supplement.index("<active-skills>")
    assert supplement.index("<active-skills>") < supplement.index("<long-term-memory>")
    assert "持续调查、执行并验证" in supplement
    assert "继续执行并验证" in second.prompt.supplements[0]


@pytest.mark.asyncio
async def test_plan_pipeline_uses_readonly_tools_and_plan_reminder() -> None:
    environment = FakeEnvironmentCollector()
    pipeline = PromptPipeline(environment_collector=environment)  # type: ignore[arg-type]
    registry = create_default_registry().subset(("read_file", "find_files", "search_code"))
    request = await pipeline.build(
        messages=(UserMessage("调查"),),
        tools=registry.definitions(),
        project_root=Path("/fixture"),
        mode=AgentMode.PLAN,
        iteration=1,
        options=PromptOptions(),
    )
    assert [tool.name for tool in request.tools] == ["read_file", "find_files", "search_code"]
    assert "当前为 Plan Mode" in request.prompt.supplements[0]
    assert "不得修改文件或执行命令" in request.prompt.supplements[0]
