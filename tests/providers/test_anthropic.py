"""Anthropic Provider 测试。"""

# ruff: noqa: E501

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEventKind
from mewcode.providers.anthropic import AnthropicProvider


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
        StreamEventKind.THINKING_DELTA,
        StreamEventKind.TEXT_DELTA,
        StreamEventKind.DONE,
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
        (StreamEventKind.THINKING_DELTA, "想"),
        (StreamEventKind.TEXT_DELTA, "答"),
        (StreamEventKind.DONE, ""),
    ]


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
