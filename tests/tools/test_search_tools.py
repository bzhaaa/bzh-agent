"""文件查找和内容搜索测试。"""

import json
from pathlib import Path

import pytest

from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolExecutor,
    create_default_registry,
)


async def execute(tmp_path: Path, name: str, arguments: dict[str, object]):
    registry = create_default_registry()
    return await ToolExecutor(registry).execute(
        ToolCall("search-1", name, json.dumps(arguments)), ToolContext(tmp_path)
    )


@pytest.mark.asyncio
async def test_find_files_is_sorted_bounded_and_skips_links(tmp_path: Path) -> None:
    for name in ("b.py", "a.py", "note.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    outside = tmp_path.parent / "outside-search"
    outside.mkdir(exist_ok=True)
    (outside / "hidden.py").write_text("hidden", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    result = await execute(tmp_path, "find_files", {"pattern": "**/*.py", "max_results": 1})
    assert result.success
    assert result.content["files"] == ["a.py"]
    assert result.content["truncated"] is True


@pytest.mark.asyncio
async def test_search_literal_regex_filter_and_long_line(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("needle 123\n" + "needle" + "x" * 1200, encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle 456", encoding="utf-8")
    literal = await execute(
        tmp_path,
        "search_code",
        {"query": "needle", "file_pattern": "*.py", "max_results": 10},
    )
    assert literal.success
    assert [match["line_number"] for match in literal.content["matches"]] == [1, 2]
    assert literal.content["line_truncated"] is True
    regex = await execute(
        tmp_path,
        "search_code",
        {"query": r"needle \d+", "regex": True, "max_results": 10},
    )
    assert regex.content["count"] == 2


@pytest.mark.asyncio
async def test_search_invalid_regex_and_pattern_are_structured(tmp_path: Path) -> None:
    invalid_regex = await execute(tmp_path, "search_code", {"query": "[", "regex": True})
    assert invalid_regex.error_code == ToolErrorCode.INVALID_PATTERN
    invalid_glob = await execute(tmp_path, "find_files", {"pattern": "../*.py"})
    assert invalid_glob.error_code == ToolErrorCode.INVALID_PATTERN
