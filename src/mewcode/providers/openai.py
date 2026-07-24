"""OpenAI Chat Completions API 适配器。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEvent, StreamEventKind
from mewcode.providers.base import DEFAULT_MAX_TOKENS


class OpenAIProvider:
    """将 OpenAI SDK 事件转换为统一流事件。"""

    def __init__(self, profile: ProviderProfile, client: Any | None = None) -> None:
        self.profile = profile
        self.client = client or openai.AsyncOpenAI(
            api_key=profile.api_key.get_secret_value(),
            base_url=str(profile.base_url),
        )

    async def close(self) -> None:
        """关闭 SDK 连接池。"""

        await self.client.close()

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[StreamEvent]:
        """发起请求并逐个产生统一事件。"""

        saw_text = False
        saw_stop = False
        stream: Any | None = None
        try:
            stream = await self.client.chat.completions.create(
                model=self.profile.model,
                messages=[
                    {"role": message.role, "content": message.content} for message in messages
                ],
                max_tokens=DEFAULT_MAX_TOKENS,
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if not isinstance(choices, list):
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                for choice in choices:
                    if getattr(choice, "finish_reason", None) is not None:
                        saw_stop = True
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    if content is None:
                        continue
                    if not isinstance(content, str):
                        raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                    if content:
                        saw_text = True
                        yield StreamEvent(StreamEventKind.TEXT_DELTA, content)
        except ProviderError:
            raise
        except openai.AuthenticationError as error:
            raise ProviderError(ProviderErrorKind.AUTHENTICATION) from error
        except openai.RateLimitError as error:
            raise ProviderError(ProviderErrorKind.RATE_LIMIT) from error
        except openai.APIConnectionError as error:
            raise ProviderError(ProviderErrorKind.CONNECTION) from error
        except openai.APIStatusError as error:
            raise ProviderError(ProviderErrorKind.SERVER) from error
        except (AttributeError, TypeError, ValueError) as error:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM) from error
        finally:
            if stream is not None:
                close = getattr(stream, "close", None)
                if close is not None:
                    await close()

        if not saw_text or not saw_stop:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        yield StreamEvent(StreamEventKind.DONE)
