"""工具注册中心和默认工具集合。"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable

from mewcode.tools.base import Tool, ToolDefinition, ToolExecutionPolicy
from mewcode.tools.edit_file import EditFileTool
from mewcode.tools.execute_command import ExecuteCommandTool
from mewcode.tools.find_files import FindFilesTool
from mewcode.tools.read_file import ReadFileTool
from mewcode.tools.search_code import SearchCodeTool
from mewcode.tools.write_file import WriteFileTool

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolRegistry:
    """按稳定顺序登记和查询工具。"""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        definition = tool.definition
        if not isinstance(getattr(tool, "policy", None), ToolExecutionPolicy):
            raise ValueError(f"工具 {definition.name} 缺少有效执行策略。")
        if not TOOL_NAME_PATTERN.fullmatch(definition.name):
            raise ValueError("工具名必须使用小写 snake_case。")
        if not definition.description.strip():
            raise ValueError("工具描述不能为空。")
        schema = definition.input_schema
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("工具参数 Schema 必须是禁止未知字段的 object。")
        if definition.name in self._tools:
            raise ValueError(f"工具名重复：{definition.name}")
        self._tools[definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def subset(self, names: Collection[str]) -> ToolRegistry:
        requested = set(names)
        missing = requested.difference(self._tools)
        if missing:
            raise ValueError(f"工具不存在：{', '.join(sorted(missing))}")
        return ToolRegistry(tool for name, tool in self._tools.items() if name in requested)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        (
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            ExecuteCommandTool(),
            FindFilesTool(),
            SearchCodeTool(),
        )
    )
