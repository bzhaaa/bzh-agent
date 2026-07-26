"""在项目文件中搜索文本或正则。"""

import asyncio
import re

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition, ToolExecutionPolicy
from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.find_files import matches_glob
from mewcode.tools.paths import ProjectPaths
from mewcode.tools.read_file import MAX_FILE_BYTES

MAX_LINE_CHARS = 1000


class SearchCodeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    regex: bool = False
    file_pattern: str = Field(default="**/*", min_length=1, max_length=1000)
    max_results: int = Field(default=200, ge=1, le=1000)


class SearchCodeTool:
    argument_model = SearchCodeArguments
    requires_approval = False
    policy = ToolExecutionPolicy.PARALLEL_READ
    definition = ToolDefinition(
        "search_code",
        "在项目文本文件中搜索字面量或正则，支持 glob 过滤。搜索内容时优先使用此工具，不要用 Shell 的 grep 或 rg 代替。",
        SearchCodeArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: SearchCodeArguments, context: ToolContext
    ) -> dict[str, object]:
        paths = ProjectPaths(context.project_root)
        paths.validate_pattern(arguments.file_pattern)
        try:
            pattern = re.compile(arguments.query if arguments.regex else re.escape(arguments.query))
        except re.error as error:
            raise ToolError(ToolErrorCode.INVALID_PATTERN, "正则表达式无效。") from error
        results: list[dict[str, object]] = []
        any_line_truncated = False
        truncated = False
        for index, (path, relative) in enumerate(paths.iter_files()):
            if not matches_glob(relative, arguments.file_pattern):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                raw = path.read_bytes()
                if b"\x00" in raw:
                    continue
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line) is None:
                    continue
                if len(results) >= arguments.max_results:
                    truncated = True
                    break
                line_truncated = len(line) > MAX_LINE_CHARS
                any_line_truncated = any_line_truncated or line_truncated
                results.append(
                    {
                        "path": relative,
                        "line_number": line_number,
                        "line": line[:MAX_LINE_CHARS],
                        "line_truncated": line_truncated,
                    }
                )
            if truncated:
                break
            if index % 50 == 0:
                await asyncio.sleep(0)
        return {
            "matches": results,
            "count": len(results),
            "truncated": truncated,
            "line_truncated": any_line_truncated,
            "summary": f"找到 {len(results)} 处匹配{'，结果已截断' if truncated else ''}。",
        }
