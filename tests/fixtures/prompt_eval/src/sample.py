"""用于提示行为评估的最小用户模块。"""

DEFAULT_TIMEOUT_SECONDS = 30


def normalize_name(name: str) -> str:
    """去掉姓名两端空白，并生成问候语。"""

    cleaned = name.strip()
    return f"Hello, {cleaned}"


def timeout_message() -> str:
    """返回当前超时设置的可读说明。"""

    return f"Timeout: {DEFAULT_TIMEOUT_SECONDS}s"

