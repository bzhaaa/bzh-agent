"""项目路径边界与原子写入测试。"""

import os
from pathlib import Path

import pytest

from mewcode.tools.errors import ToolError, ToolErrorCode
from mewcode.tools.paths import ProjectPaths, atomic_write_text


def test_paths_reject_traversal_absolute_and_external_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    paths = ProjectPaths(root)

    for value in ("../outside.txt", str(outside), "link.txt"):
        with pytest.raises(ToolError) as caught:
            paths.resolve_file(value, must_exist=True)
        assert caught.value.code == ToolErrorCode.PATH_OUTSIDE_ROOT


def test_paths_create_parent_and_enumerate_without_links_or_git(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.py").write_text("x", encoding="utf-8")
    (root / "external").symlink_to(outside, target_is_directory=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    paths = ProjectPaths(root)
    target = paths.ensure_parent("a/b/file.txt")
    target.write_text("ok", encoding="utf-8")
    assert [relative for _path, relative in paths.iter_files()] == ["a/b/file.txt"]


def test_atomic_write_preserves_mode_and_cleans_failed_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert target.stat().st_mode & 0o777 == 0o640

    original_replace = os.replace

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_write_text(target, "broken")
    monkeypatch.setattr(os, "replace", original_replace)
    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".mewcode-*"))
