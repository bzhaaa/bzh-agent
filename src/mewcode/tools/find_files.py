"""按 glob 模式查找项目文件。"""

import fnmatch

from pydantic import BaseModel, ConfigDict, Field

from mewcode.tools.base import ToolContext, ToolDefinition, ToolExecutionPolicy
from mewcode.tools.paths import ProjectPaths


class FindFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=200, ge=1, le=1000)


def matches_glob(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


class FindFilesTool:
    argument_model = FindFilesArguments
    requires_approval = False
    policy = ToolExecutionPolicy.PARALLEL_READ
    definition = ToolDefinition(
        "find_files",
        "按相对 glob 模式查找项目内普通文件。",
        FindFilesArguments.model_json_schema(),
    )

    async def execute(
        self, arguments: FindFilesArguments, context: ToolContext
    ) -> dict[str, object]:
        paths = ProjectPaths(context.project_root)
        paths.validate_pattern(arguments.pattern)
        all_matches = sorted(
            relative
            for _path, relative in paths.iter_files()
            if matches_glob(relative, arguments.pattern)
        )
        truncated = len(all_matches) > arguments.max_results
        matches = all_matches[: arguments.max_results]
        return {
            "pattern": arguments.pattern,
            "files": matches,
            "count": len(matches),
            "truncated": truncated,
            "summary": f"找到 {len(matches)} 个文件{'，结果已截断' if truncated else ''}。",
        }
