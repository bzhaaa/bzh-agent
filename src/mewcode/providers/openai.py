"""OpenAI Chat Completions API 适配器。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    AssistantMessage,
    ChatMessage,
    StreamEvent,
    StreamEventKind,
    ToolResultMessage,
    UserMessage,
)
from mewcode.providers.base import DEFAULT_MAX_TOKENS
from mewcode.tools.base import ToolCall, ToolDefinition


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

    @staticmethod
    def _messages(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
        converted: list[dict[str, object]] = []
        for message in messages:
            if isinstance(message, UserMessage):
                converted.append({"role": "user", "content": message.content})
            elif isinstance(message, AssistantMessage):
                item: dict[str, object] = {"role": "assistant", "content": message.content}
                if message.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.arguments_json,
                            },
                        }
                        for call in message.tool_calls
                    ]
                converted.append(item)
            elif isinstance(message, ToolResultMessage):
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.result.call_id,
                        "content": message.result.to_model_json(),
                    }
                )
            else:
                raise TypeError("不支持的会话消息。")
        return converted

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AsyncIterator[StreamEvent]:
        """发起请求并逐个产生统一事件。"""

        saw_text = False
        saw_stop = False
        finish_reason: str | None = None
        calls: dict[int, dict[str, str]] = {}
        stream: Any | None = None
        try:
            request: dict[str, object] = {
                "model": self.profile.model,
                "messages": self._messages(messages),
                "max_tokens": DEFAULT_MAX_TOKENS,
                "stream": True,
            }
            if tools:
                request["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                    for tool in tools
                ]
                request["tool_choice"] = "auto"
            stream = await self.client.chat.completions.create(**request)
            async for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if not isinstance(choices, list):
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                for choice in choices:
                    if getattr(choice, "index", 0) != 0:
                        raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                    reason = getattr(choice, "finish_reason", None)
                    if reason is not None:
                        if finish_reason is not None and finish_reason != reason:
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        finish_reason = reason
                        saw_stop = True
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None)
                    if content is not None and not isinstance(content, str):
                        raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                    if content:
                        saw_text = True
                        yield StreamEvent(StreamEventKind.TEXT_DELTA, content)
                    tool_calls = getattr(delta, "tool_calls", None)
                    if tool_calls is None:
                        continue
                    if not isinstance(tool_calls, list):
                        raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                    for fragment in tool_calls:
                        index = getattr(fragment, "index", None)
                        if not isinstance(index, int) or index < 0:
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        state = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        call_id = getattr(fragment, "id", None)
                        if call_id is not None:
                            if not isinstance(call_id, str) or (
                                state["id"] and state["id"] != call_id
                            ):
                                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                            state["id"] = call_id
                        call_type = getattr(fragment, "type", None)
                        if call_type not in {None, "function"}:
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        function = getattr(fragment, "function", None)
                        if function is None:
                            continue
                        name = getattr(function, "name", None)
                        if name is not None:
                            if not isinstance(name, str) or (
                                state["name"] and state["name"] != name
                            ):
                                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                            state["name"] = name
                        arguments = getattr(function, "arguments", None)
                        if arguments is not None:
                            if not isinstance(arguments, str):
                                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                            state["arguments"] += arguments
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

        if not saw_stop:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        if finish_reason == "tool_calls":
            if not calls:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
            for index in sorted(calls):
                state = calls[index]
                if not state["id"] or not state["name"]:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                try:
                    arguments = json.loads(state["arguments"])
                except (json.JSONDecodeError, TypeError) as error:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM) from error
                if not isinstance(arguments, dict):
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                yield StreamEvent(
                    StreamEventKind.TOOL_CALL,
                    tool_call=ToolCall(state["id"], state["name"], state["arguments"]),
                )
        elif finish_reason == "stop":
            if not saw_text or calls:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        else:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        yield StreamEvent(StreamEventKind.DONE)
