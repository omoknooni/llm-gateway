"""재시드의 금액 정밀도와 원자성 (M6 리뷰 P1-2·P1-3).

두 항목 모두 **DB 저장값과 Redis 카운터 문자열이 같은가**가 쟁점이라 실제 PostgreSQL 과
Redis 없이는 검증할 수 없습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import redis.asyncio as aioredis

from app.core import cache_keys
from app.core.exceptions import CounterWriteError
from app.models.enums import BudgetScope
from app.repositories.budget_repository import BudgetUsageRepository
from app.schemas.budgets import BudgetSetRequest, ReseedRequest
from app.services.budget_service import BudgetService
from tests.integration.conftest import admin_actor, seed_team, seed_user

PERIOD = "2026-09"


async def _setup(session, cache_mgr, redis_client, ctx, *, limit="1000"):
    team_id = await seed_team(session)
    admin_id = await seed_user(session, team_id, display_name="admin")
    actor = admin_actor(admin_id, team_id)
    service = BudgetService(cache_mgr, redis_client)
    await service.set_team_budget(
        session, team_id=team_id, data=BudgetSetRequest(limit_usd=limit), actor=actor, ctx=ctx
    )
    return service, team_id, actor


def _reseed(team_id, amount: str) -> ReseedRequest:
    return ReseedRequest(
        items=[
            {"scope": "TEAM", "scope_id": str(team_id), "period": PERIOD, "used_usd": amount}
        ],
        reason="통합 테스트",
    )


# ── P1-2 금액 정밀도 ──


@pytest.mark.parametrize("amount", ["812.4300", "0.0001", "1234567890.1234", "100", "0"])
async def test_db_value_and_redis_counter_agree(
    db_session, cache_mgr, redis_client, ctx, amount
):
    """`numeric(14,4)` 반올림과 `quantize()` 가 다른 값을 만들면 안 됩니다.

    다르면 운영자가 보는 내구 사본과 gateway 가 집행에 쓰는 카운터가 갈립니다.
    """
    service, team_id, actor = await _setup(db_session, cache_mgr, redis_client, ctx)
    await service.reseed(db_session, data=_reseed(team_id, amount), actor=actor, ctx=ctx)

    row = await BudgetUsageRepository(db_session).get(BudgetScope.TEAM, team_id, PERIOD)
    counter = await redis_client.get(cache_keys.budget_usage_counter("TEAM", team_id, PERIOD))

    assert row is not None
    # DB 는 numeric(14,4), 카운터는 같은 값의 10진 문자열. 둘을 Decimal 로 비교합니다.
    assert Decimal(counter) == row.used_usd, f"DB={row.used_usd} vs Redis={counter}"
    # 지수 표기가 섞이면 gateway 의 INCRBYFLOAT 가 카운터를 통째로 깨뜨립니다.
    assert "E" not in counter.upper()


async def test_counter_value_is_incrbyfloat_compatible(
    db_session, cache_mgr, redis_client, ctx
):
    """재시드가 쓴 문자열 위에 gateway 가 그대로 누적할 수 있어야 합니다."""
    service, team_id, actor = await _setup(db_session, cache_mgr, redis_client, ctx)
    await service.reseed(db_session, data=_reseed(team_id, "100"), actor=actor, ctx=ctx)

    key = cache_keys.budget_usage_counter("TEAM", team_id, PERIOD)
    # gateway 가 하는 일과 같은 연산입니다.
    after = await redis_client.incrbyfloat(key, 0.5)
    assert Decimal(str(after)) == Decimal("100.5")


# ── P1-3 원자성 ──


class _BrokenRedis:
    """파이프라인 실행만 실패시킵니다. 읽기는 정상이라 조회 경로와 구분됩니다."""

    def __init__(self, real: aioredis.Redis) -> None:
        self._real = real

    def pipeline(self, transaction: bool = False):
        return _BrokenPipeline()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _BrokenPipeline:
    def set(self, *args, **kwargs):
        return self

    async def execute(self):
        raise ConnectionError("redis down")


async def test_reseed_rolls_back_when_counter_write_fails(
    db_session, session_factory, cache_mgr, redis_client, ctx
):
    """카운터를 못 쓰면 **아무것도 바뀌지 않습니다.**

    이전 구현은 DB 를 먼저 커밋해서, Redis 실패 시 gateway 가 옛 값으로 계속 집행하는 상태가
    조용히 남았습니다(리뷰 P1-3).
    """
    service, team_id, actor = await _setup(db_session, cache_mgr, redis_client, ctx)

    broken = BudgetService(cache_mgr, _BrokenRedis(redis_client))
    with pytest.raises(CounterWriteError) as exc:
        await broken.reseed(db_session, data=_reseed(team_id, "500"), actor=actor, ctx=ctx)
    assert exc.value.status_code == 503
    assert exc.value.code == "counter_write_failed"

    # DB 에도 Redis 에도 흔적이 없어야 합니다. 다른 세션으로 확인합니다(롤백된 세션이 아니라).
    async with session_factory() as verify:
        assert await BudgetUsageRepository(verify).get(BudgetScope.TEAM, team_id, PERIOD) is None
    assert await redis_client.get(cache_keys.budget_usage_counter("TEAM", team_id, PERIOD)) is None


async def test_reseed_succeeds_after_redis_recovers(
    db_session, session_factory, cache_mgr, redis_client, ctx
):
    """재시드는 멱등합니다 — 실패 뒤 그대로 다시 부르면 됩니다. 그래서 503 이 맞는 상태 코드입니다."""
    service, team_id, actor = await _setup(db_session, cache_mgr, redis_client, ctx)

    broken = BudgetService(cache_mgr, _BrokenRedis(redis_client))
    with pytest.raises(CounterWriteError):
        await broken.reseed(db_session, data=_reseed(team_id, "500"), actor=actor, ctx=ctx)

    await service.reseed(db_session, data=_reseed(team_id, "500"), actor=actor, ctx=ctx)

    async with session_factory() as verify:
        row = await BudgetUsageRepository(verify).get(BudgetScope.TEAM, team_id, PERIOD)
    counter = await redis_client.get(cache_keys.budget_usage_counter("TEAM", team_id, PERIOD))

    assert row is not None and row.used_usd == Decimal("500.0000")
    assert Decimal(counter) == Decimal("500")


async def test_reseed_writes_audit_per_item(db_session, cache_mgr, redis_client, ctx):
    """항목마다 한 건. 묶으면 `resource_id` 로 대상을 찾을 수 없습니다(00 문서)."""
    from sqlalchemy import select

    from app.models.audit import AuditLog

    service, team_id, actor = await _setup(db_session, cache_mgr, redis_client, ctx)
    user_id = await seed_user(db_session, team_id, display_name="member")

    await service.reseed(
        db_session,
        data=ReseedRequest(
            items=[
                {"scope": "TEAM", "scope_id": str(team_id), "period": PERIOD, "used_usd": "10"},
                {"scope": "USER", "scope_id": str(user_id), "period": PERIOD, "used_usd": "20"},
            ],
            reason="오집계 정정",
        ),
        actor=actor,
        ctx=ctx,
    )

    logs = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "RESEED_BUDGET_USAGE")
        )
    ).scalars().all()

    assert len(logs) == 2
    assert {log.resource_id for log in logs} == {
        f"TEAM:{team_id}:{PERIOD}",
        f"USER:{user_id}:{PERIOD}",
    }
    assert all(log.changes["reason"] == "오집계 정정" for log in logs)
    # before/after 가 남아야 "무엇을 얼마로 고쳤는가"를 답할 수 있습니다.
    assert all("before" in log.changes and "after" in log.changes for log in logs)
