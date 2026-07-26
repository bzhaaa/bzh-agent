"""稳定系统提示和动态系统补充构建器。"""

from __future__ import annotations

from collections.abc import Sequence
from xml.sax.saxutils import escape

from mewcode.prompting.errors import PromptBuildError
from mewcode.prompting.models import (
    EnvironmentSnapshot,
    PromptChannel,
    PromptOptions,
    PromptSection,
)
from mewcode.prompting.sections import FIXED_SECTIONS

OPTION_SECTION_LIMIT = 16 * 1024
OPTION_TOTAL_LIMIT = 28 * 1024
SUPPLEMENT_LIMIT = 32 * 1024


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def _limit_error(name: str, actual: int, limit: int) -> PromptBuildError:
    return PromptBuildError(f"{name} 超过长度限制：实际 {actual} 字节，限制 {limit} 字节。")


class StablePromptBuilder:
    """校验并缓存字节稳定的系统提示。"""

    def __init__(self, sections: Sequence[PromptSection] = FIXED_SECTIONS) -> None:
        names: set[str] = set()
        priorities: set[int] = set()
        validated: list[PromptSection] = []
        for section in sections:
            name = section.name.strip()
            if not name:
                raise PromptBuildError("稳定模块名称不能为空。")
            if name in names:
                raise PromptBuildError(f"稳定模块名称重复：{name}")
            if section.priority in priorities:
                raise PromptBuildError(f"稳定模块优先级重复：{section.priority}")
            if section.channel != PromptChannel.STABLE:
                raise PromptBuildError(f"稳定模块 {name} 使用了错误通道。")
            content = section.content.strip()
            if not content:
                raise PromptBuildError(f"稳定模块 {name} 内容不能为空。")
            names.add(name)
            priorities.add(section.priority)
            validated.append(PromptSection(name, section.priority, content, section.channel))
        self.sections = tuple(sorted(validated, key=lambda item: item.priority))
        self._result = "\n\n".join(section.content for section in self.sections)

    def build(self) -> str:
        """返回实例创建时已冻结的稳定提示。"""

        return self._result


class SupplementBuilder:
    """构建当前请求唯一的、有界系统提醒。"""

    @staticmethod
    def _optional_parts(options: PromptOptions) -> tuple[str | None, str | None, str | None]:
        custom = options.custom_instructions
        custom = custom.strip() if custom and custom.strip() else None
        memory = options.long_term_memory
        memory = memory.strip() if memory and memory.strip() else None
        skills: list[str] = []
        for index, skill in enumerate(options.active_skills, start=1):
            if not skill.strip():
                raise PromptBuildError(f"active_skills 第 {index} 项不能为空白。")
            skills.append(skill.strip())
        skill_text = "\n".join(
            f'<skill index="{index}">{escape(skill)}</skill>'
            for index, skill in enumerate(skills, start=1)
        )
        return custom, skill_text or None, memory

    def validate_options(self, options: PromptOptions) -> None:
        """在不回显正文的前提下校验可选内容边界。"""

        custom, skills, memory = self._optional_parts(options)
        values = (
            ("custom_instructions", custom),
            ("active_skills", skills),
            ("long_term_memory", memory),
        )
        total = 0
        for name, value in values:
            if value is None:
                continue
            length = _byte_length(value)
            if length > OPTION_SECTION_LIMIT:
                raise _limit_error(name, length, OPTION_SECTION_LIMIT)
            total += length
        if total > OPTION_TOTAL_LIMIT:
            raise _limit_error("可选内容合计", total, OPTION_TOTAL_LIMIT)

    def build(
        self,
        snapshot: EnvironmentSnapshot,
        mode_reminder: str,
        options: PromptOptions,
    ) -> str:
        """生成一个不会保留到历史的 system reminder。"""

        self.validate_options(options)
        custom, skills, memory = self._optional_parts(options)
        dirty = "unknown" if snapshot.git_dirty is None else str(snapshot.git_dirty).lower()
        environment_lines = (
            f"项目根目录：{snapshot.project_root}",
            f"平台：{snapshot.platform}",
            f"Shell：{snapshot.shell}",
            f"日期：{snapshot.current_date}",
            f"时区：{snapshot.timezone}",
            f"Git 分支：{snapshot.git_branch}",
            f"Git dirty：{dirty}",
            f"Agent 模式：{snapshot.mode.value}",
            mode_reminder,
        )
        blocks = [
            "<system-reminder>",
            "<environment>",
            escape("\n".join(environment_lines)),
            "</environment>",
        ]
        if custom is not None:
            blocks.extend(("<custom-instructions>", escape(custom), "</custom-instructions>"))
        if skills is not None:
            blocks.extend(("<active-skills>", skills, "</active-skills>"))
        if memory is not None:
            blocks.extend(("<long-term-memory>", escape(memory), "</long-term-memory>"))
        blocks.append("</system-reminder>")
        result = "\n".join(blocks)
        length = _byte_length(result)
        if length > SUPPLEMENT_LIMIT:
            raise _limit_error("system_reminder", length, SUPPLEMENT_LIMIT)
        return result
