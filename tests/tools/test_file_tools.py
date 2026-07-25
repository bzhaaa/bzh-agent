"""读、写、改文件工具测试。"""

import hashlib
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
        ToolCall("call-1", name, json.dumps(arguments, ensure_ascii=False)), ToolContext(tmp_path)
    )


@pytest.mark.asyncio
async def test_write_read_and_overwrite_file(tmp_path: Path) -> None:
    created = await execute(
        tmp_path, "write_file", {"path": "nested/demo.txt", "content": "一\n二\n三\n"}
    )
    assert created.success
    assert created.content["operation"] == "created"
    read = await execute(
        tmp_path,
        "read_file",
        {"path": "nested/demo.txt", "start_line": 2, "line_count": 1},
    )
    assert read.success
    assert read.content["content"] == "2: 二"
    assert read.content["truncated"] is True
    overwritten = await execute(
        tmp_path, "write_file", {"path": "nested/demo.txt", "content": "替换"}
    )
    assert overwritten.content["operation"] == "overwritten"
    assert (tmp_path / "nested/demo.txt").read_text(encoding="utf-8") == "替换"


@pytest.mark.asyncio
async def test_read_rejects_directory_binary_encoding_and_range(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"a\x00b")
    (tmp_path / "invalid.txt").write_bytes(b"\xff")
    (tmp_path / "text.txt").write_text("one", encoding="utf-8")
    for path, arguments, code in (
        ("missing", {}, ToolErrorCode.NOT_FOUND),
        (".", {}, ToolErrorCode.NOT_A_FILE),
        ("binary.bin", {}, ToolErrorCode.INVALID_ENCODING),
        ("invalid.txt", {}, ToolErrorCode.INVALID_ENCODING),
        ("text.txt", {"start_line": 2}, ToolErrorCode.INVALID_ARGUMENTS),
    ):
        result = await execute(tmp_path, "read_file", {"path": path, **arguments})
        assert not result.success
        assert result.error_code == code


@pytest.mark.asyncio
async def test_edit_requires_exactly_one_match_and_preserves_failed_bytes(tmp_path: Path) -> None:
    target = tmp_path / "demo.txt"
    target.write_text("alpha beta alpha", encoding="utf-8")
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    multiple = await execute(
        tmp_path,
        "edit_file",
        {"path": "demo.txt", "old_text": "alpha", "new_text": "gamma"},
    )
    assert multiple.error_code == ToolErrorCode.NO_UNIQUE_MATCH
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
    missing = await execute(
        tmp_path,
        "edit_file",
        {"path": "demo.txt", "old_text": "none", "new_text": "gamma"},
    )
    assert missing.error_code == ToolErrorCode.NO_UNIQUE_MATCH
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
    success = await execute(
        tmp_path,
        "edit_file",
        {"path": "demo.txt", "old_text": " beta ", "new_text": " delta "},
    )
    assert success.success
    assert target.read_text(encoding="utf-8") == "alpha delta alpha"


@pytest.mark.asyncio
async def test_file_tools_cannot_follow_external_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    result = await execute(root, "write_file", {"path": "link.txt", "content": "changed"})
    assert result.error_code == ToolErrorCode.PATH_OUTSIDE_ROOT
    assert outside.read_text(encoding="utf-8") == "secret"


@pytest.mark.asyncio
async def test_file_size_limits_fail_before_modification(tmp_path: Path) -> None:
    large = tmp_path / "large.txt"
    large.write_bytes(b"x" * 1_000_001)
    read = await execute(tmp_path, "read_file", {"path": "large.txt"})
    assert read.error_code == ToolErrorCode.INVALID_ARGUMENTS
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    write = await execute(
        tmp_path, "write_file", {"path": "target.txt", "content": "x" * 1_000_001}
    )
    assert write.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert target.read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_read_write_and_edit_all_reject_external_file_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project-all"
    root.mkdir()
    outside = tmp_path / "external.txt"
    outside.write_text("alpha", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    cases = [
        ("read_file", {"path": "link.txt"}),
        ("write_file", {"path": "link.txt", "content": "changed"}),
        (
            "edit_file",
            {"path": "link.txt", "old_text": "alpha", "new_text": "changed"},
        ),
    ]
    for name, arguments in cases:
        result = await execute(root, name, arguments)
        assert result.error_code == ToolErrorCode.PATH_OUTSIDE_ROOT
    assert outside.read_text(encoding="utf-8") == "alpha"
