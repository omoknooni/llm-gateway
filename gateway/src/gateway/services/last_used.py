"""`auth.virtual_keys.last_used_at` 갱신.

gateway 가 쓰는 유일한 `auth` 컬럼입니다. **매 요청 UPDATE 하지 않습니다** — 인기 키 하나가
초당 수백 번의 row lock 을 만듭니다. 이 컬럼의 용도는 "장기 미사용 키 탐지"이므로 분 단위
정확도로 충분합니다(docs/02).

창은 프로세스 로컬이라 pod 수만큼 쓰기가 늘어납니다. 그래도 요청 수보다는 훨씬 적습니다.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.core.clock import utcnow
from gateway.schema.auth import VirtualKey

logger = structlog.get_logger(__name__)


class LastUsedTracker:
    def __init__(self, throttle_seconds: int) -> None:
        self._throttle = throttle_seconds
        self._written: dict[str, float] = {}

    def should_write(self, virtual_key_id: str) -> bool:
        now = time.monotonic()
        last = self._written.get(virtual_key_id)
        if last is not None and now - last < self._throttle:
            return False
        self._written[virtual_key_id] = now
        return True

    async def write(
        self, session_factory: async_sessionmaker[AsyncSession], virtual_key_id: str
    ) -> None:
        async with session_factory() as db:
            await db.execute(
                update(VirtualKey)
                .where(VirtualKey.id == virtual_key_id)
                .values(last_used_at=utcnow())
            )
            await db.commit()
