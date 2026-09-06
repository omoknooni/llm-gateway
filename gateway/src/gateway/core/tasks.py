"""fire-and-forget 백그라운드 태스크.

`asyncio.create_task` 의 반환값을 어디에도 담아두지 않으면 GC 가 실행 중인 태스크를 수거해
조용히 사라집니다. 여기서 강한 참조를 유지하고 완료 시 놓아줍니다.

응답 경로를 막지 않아야 하는 쓰기(사용량 기록, last_used_at 갱신)가 이 통로를 씁니다.
실패해도 client 응답에는 영향이 없어야 하므로 예외를 삼키고 로그로만 남깁니다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BackgroundTasks:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> None:
        task = asyncio.create_task(self._guard(coro, name), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guard(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("background_task.failed", task=name, error=str(exc))

    async def drain(self, timeout: float = 5.0) -> None:
        """종료 시 진행 중인 쓰기에 마지막 기회를 줍니다."""
        if not self._tasks:
            return
        done, pending = await asyncio.wait(set(self._tasks), timeout=timeout)
        if pending:
            logger.warning("background_task.abandoned_on_shutdown", count=len(pending))
