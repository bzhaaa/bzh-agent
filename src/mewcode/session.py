"""对话会话和历史事务。"""

from collections.abc import AsyncIterator

from mewcode.errors import ProviderError, ProviderErrorKind
from mewcode.models import ChatMessage, StreamEvent, StreamEventKind
from mewcode.providers import LLMProvider


class ChatSession:
    """只提交完整轮次的进程内会话。"""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self._history: list[ChatMessage] = []

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._history)

    async def stream_reply(self, user_input: str) -> AsyncIterator[StreamEvent]:
        """转发 Provider 流，并在成功完成后原子提交本轮。"""

        pending_user = ChatMessage("user", user_input)
        candidate = (*self._history, pending_user)
        response_parts: list[str] = []
        done = False

        async for event in self.provider.stream(candidate):
            if event.kind == StreamEventKind.TEXT_DELTA:
                response_parts.append(event.delta)
            elif event.kind == StreamEventKind.DONE:
                if done:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                response = "".join(response_parts)
                if not response:
                    raise ProviderError(ProviderErrorKind.INVALID_STREAM)
                done = True
                self._history.extend((pending_user, ChatMessage("assistant", response)))
            yield event

        if not done:
            raise ProviderError(ProviderErrorKind.INVALID_STREAM)
