"""Provider 工厂。"""

from collections.abc import Callable

from mewcode.config import ProviderProfile
from mewcode.errors import ConfigError
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import LLMProvider
from mewcode.providers.openai import OpenAIProvider

ProviderBuilder = Callable[[ProviderProfile], LLMProvider]

_PROVIDERS: dict[str, ProviderBuilder] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


def create_provider(profile: ProviderProfile) -> LLMProvider:
    """根据协议创建 Provider。"""

    try:
        builder = _PROVIDERS[profile.protocol]
    except KeyError as error:
        raise ConfigError(f"不支持的协议：{profile.protocol}") from error
    return builder(profile)
