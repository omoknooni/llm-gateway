"""캐시 무효화 규약 테스트.

고정하려는 규칙(07 문서 테스트 전략):
  - backend 는 지우기만 한다. 값을 쓰는 경로가 없다.
  - 삭제 실패는 요청을 실패시키지 않고 실패 테이블에 남긴다.
  - 패턴(SCAN) 삭제 API 를 노출하지 않는다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.core.cache_invalidation import CacheInvalidationManager


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.deleted: list[str] = []
        self._fail = fail

    async def delete(self, *keys: str) -> int:
        if self._fail:
            raise ConnectionError("redis unreachable")
        self.deleted.extend(keys)
        return len(keys)


class FakeSession:
    def __init__(self, sink: list) -> None:
        self._sink = sink
        self.committed = False

    def add_all(self, entries) -> None:
        self._sink.extend(entries)

    async def commit(self) -> None:
        self.committed = True


def fake_session_factory(sink: list):
    @asynccontextmanager
    async def _factory():
        yield FakeSession(sink)

    return lambda: _factory()


async def test_invalidate_deletes_requested_keys():
    redis = FakeRedis()
    mgr = CacheInvalidationManager(redis, fake_session_factory([]))

    result = await mgr.invalidate(["vk:auth:a", "vk:auth:b"])

    assert redis.deleted == ["vk:auth:a", "vk:auth:b"]
    assert result.requested == 2
    assert result.deleted == 2
    assert result.ok


async def test_invalidate_empty_is_noop():
    redis = FakeRedis()
    mgr = CacheInvalidationManager(redis, fake_session_factory([]))

    result = await mgr.invalidate([])

    assert redis.deleted == []
    assert result.requested == 0
    assert result.ok


async def test_redis_failure_is_recorded_not_raised():
    """업무 트랜잭션은 이미 커밋됐으므로 되돌리지 않고 실패만 남깁니다."""
    recorded: list = []
    mgr = CacheInvalidationManager(FakeRedis(fail=True), fake_session_factory(recorded))

    result = await mgr.invalidate(["policy:model:claude-sonnet-4"], context={"source": "test"})

    assert not result.ok
    assert result.failed_keys == ["policy:model:claude-sonnet-4"]
    assert [entry.cache_key for entry in recorded] == ["policy:model:claude-sonnet-4"]
    assert recorded[0].context == {"source": "test"}


def test_no_pattern_delete_api():
    """패턴 삭제는 의도적으로 없습니다. 팬아웃은 DB 에서 대상 키를 만들어 정확히 지웁니다."""
    for name in dir(CacheInvalidationManager):
        assert "pattern" not in name.lower()
        assert "scan" not in name.lower()


@pytest.mark.parametrize(
    ("builder", "args", "expected"),
    [
        ("vk_auth", ("deadbeef",), "vk:auth:deadbeef"),
        ("model_policy", ("claude-sonnet-4",), "policy:model:claude-sonnet-4"),
        ("budget_policy", ("TEAM", "t1"), "policy:budget:team:t1"),
        ("rate_limit_policy", ("USER", "u1", None), "policy:ratelimit:user:u1:*"),
        ("rate_limit_policy", ("GLOBAL", None, "nova-pro"), "policy:ratelimit:global:global:nova-pro"),
    ],
)
def test_cache_key_shapes(builder, args, expected):
    """키 이름은 gateway 와의 공유 계약입니다(08 문서 C2). 바뀌면 이 테스트가 먼저 깨져야 합니다."""
    from app.core import cache_keys

    assert getattr(cache_keys, builder)(*args) == expected
