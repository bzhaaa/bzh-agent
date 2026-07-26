"""新建或完整覆盖项目内文本文件。"""

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition, ToolExecutionPolicy
from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.paths import ProjectPaths, atomic_write_text

MAX_WRITE_BYTES = 1_000_000


class WriteFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    content: str


class WriteFileTool:
    argument_model = WriteFileArguments
    requires_approval = False
    policy = ToolExecutionPolicy.SERIAL_SIDE_EFFECT
    definition = ToolDefinition(
        "write_file",
        "在项目内新建或完整覆盖 UTF-8 文本文件。覆盖已有文件前必须先读取；"
        "小范围变化优先使用 edit_file。",
        WriteFileArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: WriteFileArguments, context: ToolContext
    ) -> dict[str, object]:
        encoded = arguments.content.encode("utf-8")
        if len(encoded) > MAX_WRITE_BYTES:
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "内容超过写入大小上限。")
        paths = ProjectPaths(context.project_root)
        path = paths.ensure_parent(arguments.path)
        existed = path.exists()
        if existed and not path.is_file():
            raise ToolError(ToolErrorCode.NOT_A_FILE, "目标不是普通文件。")
        try:
            atomic_write_text(path, arguments.content)
        except PermissionError as error:
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "没有权限写入文件。") from error
        except OSError as error:
            raise ToolError(ToolErrorCode.EXECUTION_FAILED, "文件写入失败。") from error
        operation = "overwritten" if existed else "created"
        return {
            "path": paths.relative(path),
            "operation": operation,
            "characters": len(arguments.content),
            "bytes": len(encoded),
            "summary": f"已{'覆盖' if existed else '新建'} {paths.relative(path)}。",
        }
