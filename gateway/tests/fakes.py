"""단위 테스트용 가짜 의존성.

통합 테스트는 실제 PostgreSQL/Redis 를 씁니다. 여기 있는 것은 **장애 조합**처럼 실물로는
만들기 번거로운 상황을 재현하기 위한 최소 구현입니다.
"""

from __future__ import annotations

import time


class FakeRedis:
    def __init__(self, *, failing: bool = False) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self.failing = failing

    def _check(self) -> None:
        if self.failing:
            raise ConnectionError("redis down")

    async def get(self, key: str):
        self._check()
        item = self._data.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at <= time.monotonic():
            del self._data[key]
            return None
        return value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._check()
        self._data[key] = (value, time.monotonic() + ttl if ttl else None)

    async def delete(self, *keys: str) -> int:
        self._check()
        return sum(1 for k in keys if self._data.pop(k, None) is not None)

    async def ping(self) -> bool:
        self._check()
        return True

    def has(self, key: str) -> bool:
        return key in self._data
