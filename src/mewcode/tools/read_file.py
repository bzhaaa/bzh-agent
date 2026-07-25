"""读取项目内 UTF-8 文本文件。"""

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition, ToolExecutionPolicy
from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.paths import ProjectPaths

MAX_FILE_BYTES = 1_000_000


class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=200, ge=1, le=1000)


class ReadFileTool:
    argument_model = ReadFileArguments
    requires_approval = False
    policy = ToolExecutionPolicy.PARALLEL_READ
    definition = ToolDefinition(
        "read_file",
        "读取项目内 UTF-8 文本文件的指定行。",
        ReadFileArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: ReadFileArguments, context: ToolContext
    ) -> dict[str, object]:
        paths = ProjectPaths(context.project_root)
        path = paths.resolve_file(arguments.path, must_exist=True)
        if not path.is_file():
            raise ToolError(ToolErrorCode.NOT_A_FILE, "目标不是普通文件。")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "文件超过读取大小上限。")
        try:
            raw = path.read_bytes()
        except PermissionError as error:
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "没有权限读取文件。") from error
        if b"\x00" in raw:
            raise ToolError(ToolErrorCode.INVALID_ENCODING, "不支持二进制文件。")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolError(
                ToolErrorCode.INVALID_ENCODING, "文件不是有效的 UTF-8 文本。"
            ) from error
        lines = text.splitlines()
        if not lines and not text:
            return {
                "path": paths.relative(path),
                "start_line": 1,
                "end_line": 0,
                "total_lines": 0,
                "content": "",
                "truncated": False,
                "summary": "文件为空。",
            }
        if arguments.start_line > len(lines):
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "起始行超过文件总行数。")
        start_index = arguments.start_line - 1
        selected = lines[start_index : start_index + arguments.line_count]
        end_line = start_index + len(selected)
        truncated = end_line < len(lines)
        return {
            "path": paths.relative(path),
            "start_line": arguments.start_line,
            "end_line": end_line,
            "total_lines": len(lines),
            "content": "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(selected, start=arguments.start_line)
            ),
            "truncated": truncated,
            "summary": f"读取第 {arguments.start_line}-{end_line} 行，共 {len(lines)} 行。",
        }
