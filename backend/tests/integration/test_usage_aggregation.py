"""사용량 집계 job (M7).

집계는 SQL 이 전부라 단위 테스트로 검증할 수 있는 게 거의 없었습니다. 여기서 처음으로
실제 데이터가 들어간 결과를 확인합니다 — 버킷 경계, NULL 사용자 매핑, 실패 분류, 멱등성.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.jobs.usage_jobs import aggregate_usage_daily, aggregate_usage_monthly
from app.models.enums import ApiDialect, UsageStatus
from app.models.usage import DailyUsageAggregate, MonthlyUsageAggregate, UsageEvent
from app.policy.usage import NO_USER_ID
from tests.integration.conftest import admin_actor, seed_team, seed_user, seed_virtual_key

KST = timezone(timedelta(hours=9))

#: 집계 기준 시각. 되돌아보기 창이 아래 이벤트들을 덮도록 고정합니다.
NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def fixed_clock(monkeypatch):
    """집계 창을 고정합니다. 실제 시각에 의존하면 내일 실패하는 테스트가 됩니다."""
    monkeypatch.setattr("app.jobs.usage_jobs.utcnow", lambda: NOW)

    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "USAGE_AGGREGATION_LOOKBACK_DAYS", 5)
    monkeypatch.setattr("app.jobs.usage_jobs.get_settings", lambda: settings)
    return NOW


async def _fixtures(session):
    team_id = await seed_team(session)
    admin_id = await seed_user(session, team_id, display_name="admin")
    user_id = await seed_user(session, team_id, display_name="member")
    vk_id = await seed_virtual_key(session, team_id=team_id, owner_id=user_id, created_by=admin_id)
    return team_id, user_id, vk_id, admin_actor(admin_id, team_id)


def _event(
    *,
    team_id,
    vk_id,
    user_id=None,
    occurred_at,
    status=UsageStatus.SUCCESS,
    model_alias="claude-sonnet-4",
    input_tokens=100,
    output_tokens=50,
    cost="0.0100",
    latency_ms=200,
) -> UsageEvent:
    """gateway 가 쓰는 것과 같은 모양의 행입니다. backend 는 평소 이 테이블에 쓰지 않습니다."""
    return UsageEvent(
        id=uuid.uuid4(),
        request_id=uuid.uuid4().hex,
        occurred_at=occurred_at,
        team_id=team_id,
        user_id=user_id,
        virtual_key_id=vk_id,
        model_alias=model_alias,
        provider_model_id="apac.anthropic.claude-sonnet-4-v1:0",
        dialect=ApiDialect.OPENAI_CHAT,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=Decimal(cost),
    )


async def test_daily_buckets_follow_utc_not_local_time(db_session, fixed_clock):
    """KST 로는 10월 1일이지만 UTC 로는 9월 30일입니다.

    로컬 날짜로 버킷을 나누면 월 집계·예산 경계와 어긋나, 같은 호출이 화면마다 다른 달에
    잡힙니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)

    # 2026-10-01 00:30 KST == 2026-09-30 15:30 UTC
    kst_midnight = datetime(2026, 10, 1, 0, 30, tzinfo=KST)
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=kst_midnight))
    # 2026-10-01 09:00 KST == 2026-10-01 00:00 UTC — 여기서부터 10월입니다.
    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 10, 1, 9, 0, tzinfo=KST),
        )
    )
    await db_session.commit()

    await aggregate_usage_daily(db_session)

    buckets = (
        await db_session.execute(
            select(DailyUsageAggregate.bucket_date).order_by(DailyUsageAggregate.bucket_date)
        )
    ).scalars().all()
    assert [b.isoformat() for b in buckets] == ["2026-09-30", "2026-10-01"]


async def test_null_user_is_mapped_to_sentinel(db_session, fixed_clock):
    """`TEAM` 소유 VK 호출은 사람에 귀속되지 않습니다.

    집계 PK 는 NULL 을 담을 수 없어 예약 UUID 로 모읍니다(07 미결정 #5 종결).
    빼버리면 사용자 축 합계가 팀 합계와 맞지 않습니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)

    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at))
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=None, occurred_at=at, cost="0.0200"))
    await db_session.commit()

    await aggregate_usage_daily(db_session)

    rows = (await db_session.execute(select(DailyUsageAggregate))).scalars().all()
    by_user = {row.user_id: row for row in rows}

    assert set(by_user) == {user_id, NO_USER_ID}
    assert by_user[NO_USER_ID].estimated_cost_usd == Decimal("0.020000")
    # 팀 합계는 두 행의 합입니다 — 어느 쪽도 빠지지 않습니다.
    assert sum(row.estimated_cost_usd for row in rows) == Decimal("0.030000")


async def test_timeout_counts_as_error(db_session, fixed_clock):
    """운영 관점에서 ERROR 와 TIMEOUT 은 둘 다 실패한 호출입니다."""
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)

    for status in (UsageStatus.SUCCESS, UsageStatus.ERROR, UsageStatus.TIMEOUT):
        db_session.add(
            _event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, status=status)
        )
    await db_session.commit()

    await aggregate_usage_daily(db_session)

    row = (await db_session.execute(select(DailyUsageAggregate))).scalar_one()
    assert row.request_count == 3
    assert row.success_count == 1
    assert row.error_count == 2


async def test_aggregation_is_idempotent(db_session, fixed_clock):
    """워터마크가 없는 대신 몇 번을 돌려도 결과가 같아야 합니다.

    이게 깨지면 재집계가 수치를 두 배로 만들고, 그때는 되돌릴 방법이 없습니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    for _ in range(3):
        db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at))
    await db_session.commit()

    await aggregate_usage_daily(db_session)
    first = (await db_session.execute(select(DailyUsageAggregate))).scalar_one()
    first_count, first_cost = first.request_count, first.estimated_cost_usd

    await aggregate_usage_daily(db_session)
    await aggregate_usage_daily(db_session)

    rows = (await db_session.execute(select(DailyUsageAggregate))).scalars().all()
    assert len(rows) == 1
    assert rows[0].request_count == first_count == 3
    assert rows[0].estimated_cost_usd == first_cost


async def test_late_arriving_event_is_picked_up_on_rerun(db_session, fixed_clock):
    """gateway 의 스풀 때문에 어제 타임스탬프의 행이 나중에 들어옵니다.

    최신 버킷만 갱신하면 그 행은 영원히 집계에서 빠집니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    yesterday = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)

    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=yesterday))
    await db_session.commit()
    await aggregate_usage_daily(db_session)

    # 집계가 이미 돈 뒤에 도착한 행
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=yesterday))
    await db_session.commit()
    await aggregate_usage_daily(db_session)

    row = (await db_session.execute(select(DailyUsageAggregate))).scalar_one()
    assert row.request_count == 2


async def test_latency_percentile_is_computed(db_session, fixed_clock):
    """p95 는 PostgreSQL 의 `percentile_disc` 로 계산합니다. 대체 DB 에서는 검증 가치가 없습니다.

    `percentile_disc` 는 **실제 관측값**을 돌려줍니다(보간하지 않습니다). n=20 에서
    `ceil(0.95 * 20) = 19` 번째 값이므로, 느린 호출이 2건이어야 p95 에 잡힙니다.
    1건이면 그건 100 분위이지 95 분위가 아닙니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    for latency in [100] * 18 + [5000] * 2:
        db_session.add(
            _event(
                team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, latency_ms=latency
            )
        )
    await db_session.commit()

    await aggregate_usage_daily(db_session)

    row = (await db_session.execute(select(DailyUsageAggregate))).scalar_one()
    assert row.avg_latency_ms == 590  # (18*100 + 2*5000) / 20
    assert row.p95_latency_ms == 5000
    # 보간값이 아니라 관측값입니다 — 있지도 않은 지연시간을 만들어내지 않습니다.
    assert row.p95_latency_ms in (100, 5000)


async def test_monthly_aggregation_matches_source(db_session, fixed_clock):
    """월 집계는 일 집계가 아니라 원천에서 계산합니다 — p95 는 합성할 수 없습니다."""
    team_id, user_id, vk_id, _ = await _fixtures(db_session)

    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 9, 30, 15, 30, tzinfo=UTC),
            cost="1.0000",
        )
    )
    for day in (1, 2):
        db_session.add(
            _event(
                team_id=team_id,
                vk_id=vk_id,
                user_id=user_id,
                occurred_at=datetime(2026, 10, day, 3, 0, tzinfo=UTC),
                cost="2.0000",
            )
        )
    await db_session.commit()

    await aggregate_usage_monthly(db_session)

    rows = (
        await db_session.execute(
            select(MonthlyUsageAggregate).order_by(MonthlyUsageAggregate.period)
        )
    ).scalars().all()
    by_period = {row.period: row for row in rows}

    assert set(by_period) == {"2026-09", "2026-10"}
    assert by_period["2026-09"].request_count == 1
    assert by_period["2026-09"].estimated_cost_usd == Decimal("1.000000")
    assert by_period["2026-10"].request_count == 2
    assert by_period["2026-10"].estimated_cost_usd == Decimal("4.000000")


async def test_monthly_aggregation_is_idempotent(db_session, fixed_clock):
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    await aggregate_usage_monthly(db_session)
    await aggregate_usage_monthly(db_session)

    rows = (await db_session.execute(select(MonthlyUsageAggregate))).scalars().all()
    assert len(rows) == 1
    assert rows[0].request_count == 1


async def test_events_outside_window_are_not_aggregated(db_session, fixed_clock):
    """되돌아보기 창 밖은 건드리지 않습니다. 매번 전체를 훑으면 비용이 무제한입니다."""
    team_id, user_id, vk_id, _ = await _fixtures(db_session)

    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 8, 1, 3, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    await aggregate_usage_daily(db_session)

    assert (await db_session.execute(select(DailyUsageAggregate))).scalars().all() == []
