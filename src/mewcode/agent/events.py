"""Agent 对外异步事件。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from mewcode.models import AgentMode, TokenUsage
from mewcode.tools.base import ToolCall, ToolResult


class AgentEventKind(StrEnum):
    MODE_CHANGED = "mode_changed"
    ITERATION_STARTED = "iteration_started"
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOKEN_USAGE = "token_usage"
    PROGRESS = "progress"
    STOPPED = "stopped"


class AgentStopReason(StrEnum):
    COMPLETED = "completed"
    ITERATION_LIMIT = "iteration_limit"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    INVALID_STREAM = "invalid_stream"
    NO_PLAN = "no_plan"
    INVALID_COMMAND = "invalid_command"


@dataclass(frozen=True, slots=True)
class AgentProgress:
    phase: Literal["requesting_model", "executing_tools", "checkpoint_committed"]
    iteration: int
    completed_tools: int = 0
    total_tools: int = 0


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    request: TokenUsage
    cumulative: TokenUsage


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: AgentEventKind
    iteration: int = 0
    mode: AgentMode = AgentMode.NORMAL
    delta: str = ""
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    usage: UsageSnapshot | None = None
    progress: AgentProgress | None = None
    stop_reason: AgentStopReason | None = None
