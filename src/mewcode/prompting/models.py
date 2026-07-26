"""结构化系统提示的供应商无关领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mewcode.models import AgentMode, ChatMessage
from mewcode.tools.base import ToolDefinition


class PromptChannel(StrEnum):
    """提示内容的缓存稳定性通道。"""

    STABLE = "stable"
    SUPPLEMENT = "supplement"


@dataclass(frozen=True, slots=True)
class PromptSection:
    """一个具有确定优先级的提示模块。"""

    name: str
    priority: int
    content: str
    channel: PromptChannel


@dataclass(frozen=True, slots=True)
class PromptOptions:
    """一次 Agent Run 使用的可选动态提示。"""

    custom_instructions: str | None = None
    active_skills: tuple[str, ...] = ()
    long_term_memory: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """可安全注入模型的有界环境快照。"""

    project_root: str
    platform: str
    shell: str
    current_date: str
    timezone: str
    git_branch: str
    git_dirty: bool | None
    mode: AgentMode


class ReminderDetail(StrEnum):
    """模式提醒的详细程度。"""

    FULL = "full"
    COMPACT = "compact"


@dataclass(frozen=True, slots=True)
class StructuredPrompt:
    """稳定系统提示和当前请求的系统级补充。"""

    stable_system: str
    supplements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromptEnvelope:
    """Agent 与 Provider 之间唯一的请求边界。"""

    prompt: StructuredPrompt
    messages: tuple[ChatMessage, ...]
    tools: tuple[ToolDefinition, ...]
