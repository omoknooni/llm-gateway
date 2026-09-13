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

    # ── 집행 카운터 (docs/08). 전부 단일 키 연산입니다. ──

    async def incr(self, key: str) -> int:
        return int(await self.incrby(key, 1))

    async def incrby(self, key: str, amount: int) -> int:
        self._check()
        current = await self.get(key)
        value = int(current or 0) + amount
        self._data[key] = (str(value), self._data.get(key, (None, None))[1])
        return value

    async def incrbyfloat(self, key: str, amount: float) -> float:
        self._check()
        current = await self.get(key)
        value = float(current or 0) + amount
        # Redis 는 지수 표기를 쓰지 않습니다. 파서가 그것을 읽지 못하는 것이 계약이라
        # 가짜도 같은 형식으로 씁니다.
        self._data[key] = (format(value, "f"), self._data.get(key, (None, None))[1])
        return value

    async def decr(self, key: str) -> int:
        return int(await self.incrby(key, -1))

    async def expire(self, key: str, ttl: int, nx: bool = False) -> bool:
        self._check()
        item = self._data.get(key)
        if item is None:
            return False
        value, expires_at = item
        if nx and expires_at is not None:
            return False
        self._data[key] = (value, time.monotonic() + ttl)
        return True

    async def delete(self, *keys: str) -> int:
        self._check()
        return sum(1 for k in keys if self._data.pop(k, None) is not None)

    async def ping(self) -> bool:
        self._check()
        return True

    def has(self, key: str) -> bool:
        return key in self._data

    def value(self, key: str) -> str | None:
        item = self._data.get(key)
        return item[0] if item else None

    def ttl(self, key: str) -> float | None:
        item = self._data.get(key)
        return item[1] if item else None
