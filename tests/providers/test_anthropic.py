"""Anthropic Provider 测试。"""

# ruff: noqa: E501

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import (
    AssistantMessage,
    ChatMessage,
    ProviderEventKind,
    TokenUsage,
    ToolResultMessage,
    UserMessage,
)
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.tools import ToolCall, ToolDefinition, ToolResult


class FakeManager:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    async def __aenter__(self) -> FakeManager:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self):
        async def iterate():
            for event in self.events:
                yield event

        return iterate()


class FakeMessages:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.arguments: dict[str, object] | None = None

    def stream(self, **kwargs: object) -> FakeManager:
        self.arguments = kwargs
        return FakeManager(self.events)


def make_profile(thinking: bool = False) -> ProviderProfile:
    return ProviderProfile.model_validate(
        {
            "name": "claude",
            "protocol": "anthropic",
            "model": "claude-test",
            "base_url": "https://api.anthropic.com",
            "api_key": "secret",
            "thinking": thinking,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "thinking,max_tokens,thinking_config",
    [(False, 4096, None), (True, 8192, {"type": "enabled", "budget_tokens": 4096})],
)
async def test_anthropic_request_and_stream_events(
    thinking: bool, max_tokens: int, thinking_config: dict[str, object] | None
) -> None:
    events = [
        SimpleNamespace(type="message_start"),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="thinking_delta", thinking="想"),
        ),
        SimpleNamespace(
            type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="答")
        ),
        SimpleNamespace(type="message_stop"),
    ]
    messages = FakeMessages(events)
    provider = AnthropicProvider(make_profile(thinking), SimpleNamespace(messages=messages))
    result = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert [event.kind for event in result] == [
        ProviderEventKind.THINKING_DELTA,
        ProviderEventKind.TEXT_DELTA,
        ProviderEventKind.DONE,
    ]
    assert messages.arguments is not None
    assert messages.arguments["model"] == "claude-test"
    assert messages.arguments["max_tokens"] == max_tokens
    assert messages.arguments["messages"] == [{"role": "user", "content": "问"}]
    assert messages.arguments.get("thinking") == thinking_config


@pytest.mark.asyncio
async def test_anthropic_rejects_empty_text_stream() -> None:
    messages = FakeMessages([SimpleNamespace(type="message_start")])
    provider = AnthropicProvider(make_profile(), SimpleNamespace(messages=messages))
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM


@pytest.mark.asyncio
async def test_anthropic_official_sdk_parses_real_sse() -> None:
    body = """event: message_start
data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","content":[],"model":"claude-test","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":1,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"想"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":"","citations":null}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"答"}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":2}}

event: message_stop
data: {"type":"message_stop"}

"""

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client = anthropic.AsyncAnthropic(
        api_key="secret", base_url="https://api.anthropic.com", http_client=http_client
    )
    provider = AnthropicProvider(make_profile(thinking=True), client)
    try:
        result = [event async for event in provider.stream([ChatMessage("user", "问")])]
    finally:
        await provider.close()
    assert [(event.kind, event.delta) for event in result] == [
        (ProviderEventKind.THINKING_DELTA, "想"),
        (ProviderEventKind.TEXT_DELTA, "答"),
        (ProviderEventKind.TOKEN_USAGE, ""),
        (ProviderEventKind.DONE, ""),
    ]
    assert result[2].usage == TokenUsage(1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type,expected_kind",
    [
        (anthropic.AuthenticationError, ProviderErrorKind.AUTHENTICATION),
        (anthropic.RateLimitError, ProviderErrorKind.RATE_LIMIT),
    ],
)
async def test_anthropic_maps_status_errors(exception_type, expected_kind) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(401, request=request)

    class RaisingMessages:
        def stream(self, **kwargs):
            raise exception_type("unsafe-secret", response=response, body=None)

    provider = AnthropicProvider(make_profile(), SimpleNamespace(messages=RaisingMessages()))
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert caught.value.kind == expected_kind
    assert "unsafe-secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_anthropic_collects_fragmented_tool_call_after_message_stop() -> None:
    events = [
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="tool_use", id="tool-1", name="read_file", input={}),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"path"'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="input_json_delta", partial_json=':"a.txt"}'),
        ),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="tool_use")),
        SimpleNamespace(type="message_stop"),
    ]
    messages = FakeMessages(events)
    provider = AnthropicProvider(make_profile(), SimpleNamespace(messages=messages))
    definition = ToolDefinition(
        "read_file",
        "读取文件",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    result = [event async for event in provider.stream([UserMessage("问")], [definition])]
    assert [event.kind for event in result] == [
        ProviderEventKind.TOOL_CALL,
        ProviderEventKind.DONE,
    ]
    assert result[0].tool_call == ToolCall("tool-1", "read_file", '{"path":"a.txt"}')
    assert messages.arguments["tools"][0]["input_schema"]["type"] == "object"


def test_anthropic_converts_and_merges_tool_results() -> None:
    first = ToolCall("a", "read_file", "{}")
    second = ToolCall("b", "find_files", "{}")
    messages = AnthropicProvider._messages(
        [
            UserMessage("检查"),
            AssistantMessage("", (first, second)),
            ToolResultMessage(ToolResult("a", "read_file", True, {"value": 1})),
            ToolResultMessage(ToolResult("b", "find_files", False, {}, error_message="失败")),
            AssistantMessage("完成"),
        ]
    )
    assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
    assert len(messages[1]["content"]) == 2
    assert len(messages[2]["content"]) == 2
    assert messages[2]["content"][1]["is_error"] is True


@pytest.mark.asyncio
async def test_anthropic_rejects_unclosed_tool_block() -> None:
    events = [
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="tool_use", id="tool-1", name="read_file", input={}),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="input_json_delta", partial_json="{}"),
        ),
        SimpleNamespace(type="message_stop"),
    ]
    provider = AnthropicProvider(make_profile(), SimpleNamespace(messages=FakeMessages(events)))
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in provider.stream([UserMessage("问")])]
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM


@pytest.mark.asyncio
async def test_anthropic_usage_includes_cache_tokens() -> None:
    events = [
        SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=2,
                    cache_creation_input_tokens=3,
                    cache_read_input_tokens=4,
                )
            ),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="答"),
        ),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(output_tokens=5),
        ),
        SimpleNamespace(type="message_stop"),
    ]
    provider = AnthropicProvider(
        make_profile(),
        SimpleNamespace(messages=FakeMessages(events)),
    )
    result = [event async for event in provider.stream([UserMessage("问")])]
    usage = next(event.usage for event in result if event.usage is not None)
    assert usage == TokenUsage(9, 5)


@pytest.mark.asyncio
async def test_anthropic_preserves_multiple_tool_block_order() -> None:
    events = []
    for index, (call_id, name) in enumerate((("a", "read_file"), ("b", "find_files"))):
        events.extend(
            [
                SimpleNamespace(
                    type="content_block_start",
                    index=index,
                    content_block=SimpleNamespace(
                        type="tool_use",
                        id=call_id,
                        name=name,
                        input={},
                    ),
                ),
                SimpleNamespace(
                    type="content_block_delta",
                    index=index,
                    delta=SimpleNamespace(type="input_json_delta", partial_json="{}"),
                ),
                SimpleNamespace(type="content_block_stop", index=index),
            ]
        )
    events.extend(
        [
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="tool_use"),
            ),
            SimpleNamespace(type="message_stop"),
        ]
    )
    provider = AnthropicProvider(
        make_profile(),
        SimpleNamespace(messages=FakeMessages(events)),
    )
    result = [event async for event in provider.stream([UserMessage("问")])]
    calls = [event.tool_call for event in result if event.tool_call is not None]
    assert [call.id for call in calls] == ["a", "b"]
