"""工具系统的稳定错误分类。"""

from enum import StrEnum


class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_JSON = "invalid_json"
    INVALID_ARGUMENTS = "invalid_arguments"
    PATH_OUTSIDE_ROOT = "path_outside_root"
    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    INVALID_ENCODING = "invalid_encoding"
    NO_UNIQUE_MATCH = "no_unique_match"
    INVALID_PATTERN = "invalid_pattern"
    PERMISSION_DENIED = "permission_denied"
    USER_REJECTED = "user_rejected"
    TIMEOUT = "timeout"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


class ToolError(Exception):
    """可以安全转换成模型工具结果的领域错误。"""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        self.code = code
        self.safe_message = message[:1000]
        super().__init__(self.safe_message)
