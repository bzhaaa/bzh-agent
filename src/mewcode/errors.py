"""应用错误类型。"""

from enum import StrEnum


class ConfigError(Exception):
    """表示用户可以修复的配置错误。"""


class ProviderErrorKind(StrEnum):
    """跨供应商统一的错误分类。"""

    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    CONNECTION = "connection"
    SERVER = "server"
    INVALID_STREAM = "invalid_stream"


_PROVIDER_MESSAGES = {
    ProviderErrorKind.AUTHENTICATION: "认证失败，请检查 API Key。",
    ProviderErrorKind.RATE_LIMIT: "请求受到限流，请稍后重试。",
    ProviderErrorKind.CONNECTION: "无法连接模型服务，请检查网络和 base_url。",
    ProviderErrorKind.SERVER: "模型服务拒绝或无法完成请求，请检查模型和服务配置。",
    ProviderErrorKind.INVALID_STREAM: "模型返回了无效的流式响应。",
}


class ProviderError(Exception):
    """不暴露供应商响应正文的统一错误。"""

    def __init__(self, kind: ProviderErrorKind) -> None:
        self.kind = kind
        super().__init__(_PROVIDER_MESSAGES[kind])
