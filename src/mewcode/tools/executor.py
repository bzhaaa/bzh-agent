"""工具参数校验、确认、超时和错误隔离。"""

from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from mewcode.tools.base import CommandApprovalRequest, ToolCall, ToolContext, ToolResult
from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.registry import ToolRegistry

DEFAULT_TOOL_TIMEOUT = 30.0


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    @staticmethod
    def _failure(call: ToolCall, code: ToolErrorCode, message: str) -> ToolResult:
        return ToolResult(
            call.id,
            call.name,
            False,
            {},
            error_code=code,
            error_message=message[:1000],
        )

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolResult:
        tool = self.registry.get(call.name)
        if tool is None:
            return self._failure(call, ToolErrorCode.UNKNOWN_TOOL, "未知工具。")
        try:
            raw_arguments = json.loads(call.arguments_json)
        except (json.JSONDecodeError, TypeError):
            return self._failure(call, ToolErrorCode.INVALID_JSON, "工具参数不是有效 JSON。")
        if not isinstance(raw_arguments, dict):
            return self._failure(
                call, ToolErrorCode.INVALID_JSON, "工具参数 JSON 根值必须是 object。"
            )
        try:
            arguments = tool.argument_model.model_validate(raw_arguments)
        except ValidationError:
            return self._failure(
                call, ToolErrorCode.INVALID_ARGUMENTS, "工具参数缺失、类型错误或包含未知字段。"
            )
        if tool.requires_approval:
            request = CommandApprovalRequest(
                command=str(arguments.command),
                cwd=str(context.project_root),
                timeout_seconds=float(arguments.timeout_seconds),
            )
            approved = await context.approval_handler(request)
            if not approved:
                return self._failure(call, ToolErrorCode.USER_REJECTED, "用户拒绝执行命令。")
        timeout = float(getattr(arguments, "timeout_seconds", DEFAULT_TOOL_TIMEOUT)) + 2
        try:
            async with asyncio.timeout(timeout):
                content = await tool.execute(arguments, context)
        except asyncio.CancelledError:
            raise
        except ToolError as error:
            return self._failure(call, error.code, error.safe_message)
        except TimeoutError:
            return self._failure(call, ToolErrorCode.TIMEOUT, "工具执行超时。")
        except Exception:
            return self._failure(call, ToolErrorCode.INTERNAL_ERROR, "工具执行发生内部错误。")
        truncated = bool(content.get("truncated", False))
        return ToolResult(call.id, call.name, True, content, truncated=truncated)
