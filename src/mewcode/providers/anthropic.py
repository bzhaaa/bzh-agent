"""Anthropic Messages API 适配器。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEvent, StreamEventKind
from mewcode.providers.base import (
    DEFAULT_MAX_TOKENS,
    THINKING_BUDGET_TOKENS,
    THINKING_MAX_TOKENS,
)


class AnthropicProvider:
    """将 Anthropic SDK 事件转换为统一流事件。"""

    def __init__(self, profile: ProviderProfile, client: Any | None = None) -> None:
        self.profile = profile
        self.client = client or anthropic.AsyncAnthropic(
            api_key=profile.api_key.get_secret_value(),
            base_url=str(profile.base_url),
        )

    def _request_arguments(self, messages: Sequence[ChatMessage]) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "model": self.profile.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if self.profile.thinking:
            arguments["max_tokens"] = THINKING_MAX_TOKENS
            arguments["thinking"] = {
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS,
            }
        return arguments

    async def close(self) -> None:
        """关闭 SDK 连接池。"""

        await self.client.close()

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        """发起请求并逐个产生统一事件。"""

        saw_text = False
        saw_stop = False
        try:
            manager = self.client.messages.stream(**self._request_arguments(messages))
            async with manager as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "message_stop":
                        saw_stop = True
                        continue
                    if event_type != "content_block_delta":
                        continue
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", None)
                        if not isinstance(text, str):
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        if text:
                            saw_text = True
                            yield StreamEvent(StreamEventKind.TEXT_DELTA, text)
                    elif delta_type == "thinking_delta":
                        thinking = getattr(delta, "thinking", None)
                        if not isinstance(thinking, str):
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        if thinking:
                            yield StreamEvent(StreamEventKind.THINKING_DELTA, thinking)
                    elif delta_type in {"signature_delta", "input_json_delta", "citations_delta"}:
                        continue
                    else:
                        raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        except ProviderError:
            raise
        except anthropic.AuthenticationError as error:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION) from error
        except anthropic.RateLimitError as error:
            raise ProviderError(ProviderErrorKind.RATE_LIMIT) from error
        except anthropic.APIConnectionError as error:
            raise ProviderError(ProviderErrorKind.CONNECTION) from error
        except anthropic.APIStatusError as error:
            raise ProviderError(ProviderErrorKind.SERVER) from error
        except (AttributeError, TypeError, ValueError) as error:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM) from error

        if not saw_text or not saw_stop:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        yield StreamEvent(StreamEventKind.DONE)
