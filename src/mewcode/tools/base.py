"""供应商无关的工具接口与领域对象。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from mewcode.tools.errors import ToolErrorCode

MODEL_RESULT_LIMIT = 64_000
SUMMARY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    success: bool
    content: dict[str, object]
    error_code: ToolErrorCode | None = None
    error_message: str | None = None
    truncated: bool = False

    def to_model_json(self) -> str:
        """生成字段稳定且长度有界的 JSON。"""

        payload: dict[str, object] = {
            "tool_name": self.tool_name,
            "call_id": self.call_id,
            "success": self.success,
            "content": self.content,
            "truncated": self.truncated,
        }
        if self.error_code is not None:
            payload["error_code"] = self.error_code.value
        if self.error_message is not None:
            payload["error_message"] = self.error_message[:1000]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) <= MODEL_RESULT_LIMIT:
            return encoded
        payload["content"] = {"summary": "工具结果过长，已截断。"}
        payload["truncated"] = True
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def summary(self) -> str:
        """生成适合终端记录的有界摘要。"""

        if not self.success:
            return (self.error_message or "工具执行失败")[:SUMMARY_LIMIT]
        summary = self.content.get("summary")
        if isinstance(summary, str):
            return summary[:SUMMARY_LIMIT]
        return json.dumps(self.content, ensure_ascii=False, sort_keys=True)[:SUMMARY_LIMIT]


@dataclass(frozen=True, slots=True)
class CommandApprovalRequest:
    command: str
    cwd: str
    timeout_seconds: float


ApprovalHandler = Callable[[CommandApprovalRequest], Awaitable[bool]]


async def reject_commands(_request: CommandApprovalRequest) -> bool:
    """默认拒绝命令，防止缺少 UI 绑定时静默执行。"""

    return False


@dataclass(frozen=True, slots=True)
class ToolContext:
    project_root: Path
    approval_handler: ApprovalHandler = reject_commands


class Tool(Protocol):
    definition: ToolDefinition
    argument_model: type[BaseModel]
    requires_approval: bool

    async def execute(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]: ...
