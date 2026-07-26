"""稳定提示与动态补充构建测试。"""

from dataclasses import FrozenInstanceError

import pytest

from mewcode.agent import AgentMode
from mewcode.prompting import (
    FIXED_SECTIONS,
    EnvironmentSnapshot,
    PromptBuildError,
    PromptChannel,
    PromptOptions,
    PromptSection,
    StablePromptBuilder,
    SupplementBuilder,
)


def snapshot() -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        project_root="~/project",
        platform="TestOS",
        shell="zsh",
        current_date="2026-07-26",
        timezone="CST",
        git_branch="main",
        git_dirty=True,
        mode=AgentMode.NORMAL,
    )


def test_prompt_models_are_frozen_and_options_default_empty() -> None:
    options = PromptOptions()
    assert options.custom_instructions is None
    assert options.active_skills == ()
    assert options.long_term_memory is None
    with pytest.raises(FrozenInstanceError):
        options.custom_instructions = "changed"  # type: ignore[misc]


def test_stable_sections_are_complete_sorted_and_byte_stable() -> None:
    builder = StablePromptBuilder()
    first = builder.build()
    second = builder.build()
    assert first is second
    assert [section.name for section in builder.sections] == [
        "identity",
        "system_constraints",
        "task_mode",
        "action_execution",
        "tool_usage",
        "tone_style",
        "text_output",
    ]
    assert all(section.content for section in FIXED_SECTIONS)
    assert first.encode() == second.encode()
    assert first.count("\n\n") == 6


@pytest.mark.parametrize(
    "sections,match",
    [
        (
            (
                PromptSection("same", 1, "a", PromptChannel.STABLE),
                PromptSection("same", 2, "b", PromptChannel.STABLE),
            ),
            "名称重复",
        ),
        (
            (
                PromptSection("a", 1, "a", PromptChannel.STABLE),
                PromptSection("b", 1, "b", PromptChannel.STABLE),
            ),
            "优先级重复",
        ),
        ((PromptSection("a", 1, " ", PromptChannel.STABLE),), "内容不能为空"),
        ((PromptSection("a", 1, "a", PromptChannel.SUPPLEMENT),), "错误通道"),
    ],
)
def test_invalid_stable_sections_are_rejected(
    sections: tuple[PromptSection, ...], match: str
) -> None:
    with pytest.raises(PromptBuildError, match=match):
        StablePromptBuilder(sections)


def test_supplement_orders_optional_content_and_escapes_xml() -> None:
    result = SupplementBuilder().build(
        snapshot(),
        "当前提醒 <保持>",
        PromptOptions(
            custom_instructions="自定义 </system-reminder>",
            active_skills=("技能 A <x>", "技能 B"),
            long_term_memory="长期 & 记忆",
        ),
    )
    assert result.startswith("<system-reminder>\n<environment>")
    assert result.endswith("</system-reminder>")
    assert result.count("<system-reminder>") == 1
    assert "&lt;/system-reminder&gt;" in result
    assert "当前提醒 &lt;保持&gt;" in result
    assert '<skill index="1">技能 A &lt;x&gt;</skill>' in result
    assert result.index("<environment>") < result.index("<custom-instructions>")
    assert result.index("<custom-instructions>") < result.index("<active-skills>")
    assert result.index("<active-skills>") < result.index("<long-term-memory>")


def test_empty_optional_sections_are_omitted() -> None:
    result = SupplementBuilder().build(
        snapshot(),
        "提醒",
        PromptOptions(custom_instructions=" ", long_term_memory="\n"),
    )
    assert "custom-instructions" not in result
    assert "active-skills" not in result
    assert "long-term-memory" not in result


def test_option_limits_use_utf8_bytes_without_leaking_content() -> None:
    secret = "密" * 6000
    with pytest.raises(PromptBuildError) as caught:
        SupplementBuilder().validate_options(PromptOptions(custom_instructions=secret))
    message = str(caught.value)
    assert "16384" in message
    assert secret[:20] not in message

    with pytest.raises(PromptBuildError, match="不能为空白"):
        SupplementBuilder().validate_options(PromptOptions(active_skills=(" ",)))


def test_option_total_and_supplement_limits_are_enforced() -> None:
    builder = SupplementBuilder()
    with pytest.raises(PromptBuildError, match="可选内容合计"):
        builder.validate_options(
            PromptOptions(
                custom_instructions="a" * 10_000,
                active_skills=("b" * 9_000,),
                long_term_memory="c" * 10_000,
            )
        )
    huge_snapshot = EnvironmentSnapshot(
        project_root="x" * 33_000,
        platform="p",
        shell="s",
        current_date="2026-07-26",
        timezone="UTC",
        git_branch="main",
        git_dirty=False,
        mode=AgentMode.NORMAL,
    )
    with pytest.raises(PromptBuildError, match="system_reminder"):
        builder.build(huge_snapshot, "提醒", PromptOptions())
