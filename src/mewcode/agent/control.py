"""单次 Agent Run 的显式取消控制。"""

import asyncio
from typing import TypeVar

T = TypeVar("T")


class AgentRunCancelled(Exception):
    """用户显式取消了当前 Agent Run。"""


class AgentRunControl:
    def __init__(self) -> None:
        self._cancelled = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()


async def wait_with_control(work: asyncio.Task[T], control: AgentRunControl) -> T:
    """让一个工作任务与显式取消信号竞争，并回收未胜出的等待任务。"""

    cancelled = asyncio.create_task(control.wait_cancelled())
    try:
        done, _ = await asyncio.wait((work, cancelled), return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return await work
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        raise AgentRunCancelled
    except asyncio.CancelledError:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        raise
    finally:
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
