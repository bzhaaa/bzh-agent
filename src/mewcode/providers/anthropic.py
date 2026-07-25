"""Anthropic Messages API 适配器。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic

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
from mewcode.providers.base import (
    DEFAULT_MAX_TOKENS,
    THINKING_BUDGET_TOKENS,
    THINKING_MAX_TOKENS,
)
from mewcode.tools.base import ToolCall, ToolDefinition


class AnthropicProvider:
    """将 Anthropic SDK 事件转换为统一流事件。"""

    def __init__(self, profile: ProviderProfile, client: Any | None = None) -> None:
        self.profile = profile
        self.client = client or anthropic.AsyncAnthropic(
            api_key=profile.api_key.get_secret_value(),
            base_url=str(profile.base_url),
        )

    @staticmethod
    def _messages(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
        converted: list[dict[str, object]] = []
        for message in messages:
            if isinstance(message, UserMessage):
                role = "user"
                content: object = message.content
            elif isinstance(message, AssistantMessage):
                role = "assistant"
                if message.tool_calls:
                    blocks: list[dict[str, object]] = []
                    if message.content:
                        blocks.append({"type": "text", "text": message.content})
                    blocks.extend(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": json.loads(call.arguments_json),
                        }
                        for call in message.tool_calls
                    )
                    content = blocks
                else:
                    content = message.content
            elif isinstance(message, ToolResultMessage):
                role = "user"
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.result.call_id,
                        "content": message.result.to_model_json(),
                        "is_error": not message.result.success,
                    }
                ]
            else:
                raise TypeError("不支持的会话消息。")

            if converted and converted[-1]["role"] == role:
                previous = converted[-1]["content"]
                previous_blocks = (
                    previous if isinstance(previous, list) else [{"type": "text", "text": previous}]
                )
                new_blocks = (
                    content if isinstance(content, list) else [{"type": "text", "text": content}]
                )
                converted[-1]["content"] = [*previous_blocks, *new_blocks]
            else:
                converted.append({"role": role, "content": content})
        return converted

    def _request_arguments(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "model": self.profile.model,
            "messages": self._messages(messages),
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if tools:
            arguments["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
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

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> AsyncIterator[StreamEvent]:
        """发起请求并逐个产生统一事件。"""

        saw_text = False
        saw_stop = False
        stop_reason: str | None = None
        calls: dict[int, dict[str, object]] = {}
        try:
            manager = self.client.messages.stream(**self._request_arguments(messages, tools))
            async with manager as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "message_stop":
                        saw_stop = True
                        continue
                    if event_type == "message_delta":
                        reason = getattr(getattr(event, "delta", None), "stop_reason", None)
                        if reason is not None:
                            if stop_reason is not None and stop_reason != reason:
                                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                            stop_reason = reason
                        continue
                    if event_type == "content_block_start":
                        index = getattr(event, "index", None)
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) != "tool_use":
                            continue
                        if not isinstance(index, int) or index in calls:
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        call_id = getattr(block, "id", None)
                        name = getattr(block, "name", None)
                        initial_input = getattr(block, "input", None)
                        if (
                            not isinstance(call_id, str)
                            or not isinstance(name, str)
                            or initial_input != {}
                        ):
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        calls[index] = {
                            "id": call_id,
                            "name": name,
                            "arguments": "",
                            "closed": False,
                        }
                        continue
                    if event_type == "content_block_stop":
                        index = getattr(event, "index", None)
                        if index in calls:
                            if calls[index]["closed"]:
                                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                            calls[index]["closed"] = True
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
                    elif delta_type == "input_json_delta":
                        index = getattr(event, "index", None)
                        partial_json = getattr(delta, "partial_json", None)
                        if index not in calls or not isinstance(partial_json, str):
                            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                        calls[index]["arguments"] = str(calls[index]["arguments"]) + partial_json
                    elif delta_type in {"signature_delta", "citations_delta"}:
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

        if not saw_stop:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        if calls:
            if stop_reason not in {None, "tool_use"}:
                raise ProviderError(ProviderErrorKind.INVALID_STREAM)
            for index in sorted(calls):
                state = calls[index]
                if not state["closed"]:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                arguments_json = str(state["arguments"])
                try:
                    arguments = json.loads(arguments_json)
                except json.JSONDecodeError as error:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM) from error
                if not isinstance(arguments, dict):
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                yield StreamEvent(
                    StreamEventKind.TOOL_CALL,
                    tool_call=ToolCall(str(state["id"]), str(state["name"]), arguments_json),
                )
        elif not saw_text or stop_reason not in {None, "end_turn", "stop_sequence"}:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
        yield StreamEvent(StreamEventKind.DONE)
