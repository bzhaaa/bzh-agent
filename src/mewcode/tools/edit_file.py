"""通过唯一原文匹配修改项目内文本文件。"""

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition
from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.paths import ProjectPaths, atomic_write_text
from mewcode.tools.write_file import MAX_WRITE_BYTES


class EditFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    old_text: str = Field(min_length=1)
    new_text: str


class EditFileTool:
    argument_model = EditFileArguments
    requires_approval = False
    definition = ToolDefinition(
        "edit_file",
        "在项目内文本文件中唯一匹配原文并替换一次。",
        EditFileArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: EditFileArguments, context: ToolContext
    ) -> dict[str, object]:
        paths = ProjectPaths(context.project_root)
        path = paths.resolve_file(arguments.path, must_exist=True)
        if not path.is_file():
            raise ToolError(ToolErrorCode.NOT_A_FILE, "目标不是普通文件。")
        if path.stat().st_size > MAX_WRITE_BYTES:
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "文件超过编辑大小上限。")
        try:
            original_bytes = path.read_bytes()
            original = original_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolError(
                ToolErrorCode.INVALID_ENCODING, "文件不是有效的 UTF-8 文本。"
            ) from error
        except PermissionError as error:
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "没有权限读取文件。") from error
        matches = original.count(arguments.old_text)
        if matches != 1:
            raise ToolError(
                ToolErrorCode.NO_UNIQUE_MATCH,
                f"原文匹配 {matches} 次，必须恰好匹配一次；文件未修改。",
            )
        updated = original.replace(arguments.old_text, arguments.new_text, 1)
        if len(updated.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "替换后内容超过大小上限。")
        try:
            atomic_write_text(path, updated)
        except PermissionError as error:
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "没有权限修改文件。") from error
        except OSError as error:
            raise ToolError(ToolErrorCode.EXECUTION_FAILED, "文件修改失败。") from error
        return {
            "path": paths.relative(path),
            "matches": 1,
            "before_characters": len(original),
            "after_characters": len(updated),
            "summary": f"已修改 {paths.relative(path)}，替换 1 处。",
        }
