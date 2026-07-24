"""OpenAI Provider 测试。"""

# ruff: noqa: E501

from types import SimpleNamespace

import httpx
import openai
import pytest

from mewcode.config import ProviderProfile
from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEventKind
from mewcode.providers.openai import OpenAIProvider


class FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.closed = False

    def __aiter__(self):
        async def iterate():
            for chunk in self.chunks:
                yield chunk

        return iterate()

    async def close(self) -> None:
        self.closed = True


class FakeCompletions:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.arguments: dict[str, object] | None = None
        self.stream: FakeStream | None = None

    async def create(self, **kwargs: object) -> FakeStream:
        self.arguments = kwargs
        self.stream = FakeStream(self.chunks)
        return self.stream


def make_profile() -> ProviderProfile:
    return ProviderProfile.model_validate(
        {
            "name": "openai",
            "protocol": "openai",
            "model": "gpt-test",
            "base_url": "https://api.example.com/v1",
            "api_key": "secret",
        }
    )


@pytest.mark.asyncio
async def test_openai_request_and_stream_events() -> None:
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=None)]
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="你"), finish_reason=None)]
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="好"), finish_reason="stop")]
        ),
    ]
    completions = FakeCompletions(chunks)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAIProvider(make_profile(), client)
    result = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert [(event.kind, event.delta) for event in result] == [
        (StreamEventKind.TEXT_DELTA, "你"),
        (StreamEventKind.TEXT_DELTA, "好"),
        (StreamEventKind.DONE, ""),
    ]
    assert completions.arguments == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "问"}],
        "max_tokens": 4096,
        "stream": True,
    }
    assert completions.stream is not None
    assert completions.stream.closed


@pytest.mark.asyncio
async def test_openai_rejects_empty_text_stream() -> None:
    completions = FakeCompletions([SimpleNamespace(choices=[])])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAIProvider(make_profile(), client)
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert caught.value.kind == ProviderErrorKind.INVALID_STREAM


@pytest.mark.asyncio
async def test_openai_official_sdk_parses_real_sse() -> None:
    body = """data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-test","choices":[{"index":0,"delta":{"role":"assistant","content":"你"},"finish_reason":null}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-test","choices":[{"index":0,"delta":{"content":"好"},"finish_reason":null}]}

data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-test","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]

"""

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client = openai.AsyncOpenAI(
        api_key="secret", base_url="https://api.example.com/v1", http_client=http_client
    )
    provider = OpenAIProvider(make_profile(), client)
    try:
        result = [event async for event in provider.stream([ChatMessage("user", "问")])]
    finally:
        await provider.close()
    assert [(event.kind, event.delta) for event in result] == [
        (StreamEventKind.TEXT_DELTA, "你"),
        (StreamEventKind.TEXT_DELTA, "好"),
        (StreamEventKind.DONE, ""),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type,expected_kind",
    [
        (openai.AuthenticationError, ProviderErrorKind.AUTHENTICATION),
        (openai.RateLimitError, ProviderErrorKind.RATE_LIMIT),
    ],
)
async def test_openai_maps_status_errors(exception_type, expected_kind) -> None:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(401, request=request)

    class RaisingCompletions:
        async def create(self, **kwargs):
            raise exception_type("unsafe-secret", response=response, body=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=RaisingCompletions()))
    provider = OpenAIProvider(make_profile(), client)
    with pytest.raises(ProviderError) as caught:
        _ = [event async for event in provider.stream([ChatMessage("user", "问")])]
    assert caught.value.kind == expected_kind
    assert "unsafe-secret" not in str(caught.value)
