"""项目路径边界和原子文本写入。"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePath

from mewcode.tools.errors import ToolError, ToolErrorCode


class ProjectPaths:
    """只解析项目根目录内的用户路径。"""

    def __init__(self, root: Path) -> None:
        try:
            self.root = root.resolve(strict=True)
        except OSError as error:
            raise ToolError(ToolErrorCode.NOT_FOUND, "项目根目录不存在。") from error
        if not self.root.is_dir():
            raise ToolError(ToolErrorCode.NOT_A_FILE, "项目根路径不是目录。")

    def _candidate(self, user_path: str) -> Path:
        if not user_path or "\x00" in user_path:
            raise ToolError(ToolErrorCode.INVALID_ARGUMENTS, "路径不能为空。")
        path = Path(user_path)
        if path.is_absolute() or ".." in PurePath(user_path).parts:
            raise ToolError(ToolErrorCode.PATH_OUTSIDE_ROOT, "路径必须位于项目根目录内。")
        return self.root / path

    def resolve_file(self, user_path: str, *, must_exist: bool) -> Path:
        candidate = self._candidate(user_path)
        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError as error:
            raise ToolError(ToolErrorCode.NOT_FOUND, "路径不存在。") from error
        except PermissionError as error:
            raise ToolError(ToolErrorCode.PERMISSION_DENIED, "没有权限访问该路径。") from error
        except OSError as error:
            raise ToolError(ToolErrorCode.EXECUTION_FAILED, "无法解析该路径。") from error
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ToolError(
                ToolErrorCode.PATH_OUTSIDE_ROOT, "路径解析后超出项目根目录。"
            ) from error
        return resolved

    def relative(self, path: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(self.root).as_posix()
        except ValueError as error:
            raise ToolError(ToolErrorCode.PATH_OUTSIDE_ROOT, "路径不属于项目。") from error

    def ensure_parent(self, user_path: str) -> Path:
        """安全创建目标的项目内父目录。"""

        target = self.resolve_file(user_path, must_exist=False)
        relative_parent = target.relative_to(self.root).parent
        current = self.root
        for part in relative_parent.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                resolved = current.resolve(strict=True)
                try:
                    resolved.relative_to(self.root)
                except ValueError as error:
                    raise ToolError(
                        ToolErrorCode.PATH_OUTSIDE_ROOT, "父目录符号链接超出项目根目录。"
                    ) from error
                if not resolved.is_dir():
                    raise ToolError(ToolErrorCode.NOT_A_FILE, "父路径不是目录。")
                current = resolved
            else:
                try:
                    current.mkdir()
                except PermissionError as error:
                    raise ToolError(ToolErrorCode.PERMISSION_DENIED, "无法创建父目录。") from error
        return self.resolve_file(user_path, must_exist=False)

    @staticmethod
    def validate_pattern(pattern: str) -> None:
        if not pattern or Path(pattern).is_absolute() or ".." in PurePath(pattern).parts:
            raise ToolError(ToolErrorCode.INVALID_PATTERN, "模式必须是项目内相对 glob。")

    def iter_files(self) -> Iterator[tuple[Path, str]]:
        """稳定枚举普通文件，不进入 .git 或符号链接目录。"""

        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            base = Path(directory)
            dirnames[:] = sorted(
                name for name in dirnames if name != ".git" and not (base / name).is_symlink()
            )
            for name in sorted(filenames):
                candidate = base / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                resolved = self.resolve_file(self.relative(candidate), must_exist=True)
                yield resolved, self.relative(resolved)


def atomic_write_text(path: Path, content: str) -> None:
    """在目标同目录写入并原子替换。"""

    mode: int | None = None
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".mewcode-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
