"""사용량 조회 정확성 (M7 리뷰).

리뷰가 지적한 네 가지를 실제 데이터로 고정합니다.

- lookback 밖 원천이 backfill 로 들어오는가 (P1-1)
- 부분 월 trend 가 기간 밖 사용량을 섞지 않는가 (P1-2)
- overview 의 합계와 상위 목록이 같은 스냅샷인가 (P2-1)
- 공통 필터가 모든 엔드포인트에서 실제로 동작하는가, 기간 경계가 정확한가 (P2-2)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.jobs.backfill import run_backfill
from app.jobs.usage_jobs import aggregate_usage_daily, earliest_event_date
from app.models.enums import ApiDialect, UsageStatus
from app.models.usage import DailyUsageAggregate, UsageEvent
from app.policy.usage import TrendGranularity, UsageAxis, UsageMetric
from app.repositories.usage_repository import UsageFilter
from app.services.usage_service import UsageService
from tests.integration.conftest import admin_actor, seed_team, seed_user, seed_virtual_key

NOW = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.jobs.usage_jobs.utcnow", lambda: NOW)
    monkeypatch.setattr("app.jobs.backfill.utcnow", lambda: NOW)

    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "USAGE_AGGREGATION_LOOKBACK_DAYS", 3)
    monkeypatch.setattr("app.jobs.usage_jobs.get_settings", lambda: settings)
    monkeypatch.setattr("app.jobs.backfill.get_settings", lambda: settings)
    return NOW


async def _fixtures(session):
    team_id = await seed_team(session)
    admin_id = await seed_user(session, team_id, display_name="admin")
    user_id = await seed_user(session, team_id, display_name="member")
    vk_id = await seed_virtual_key(session, team_id=team_id, owner_id=user_id, created_by=admin_id)
    return team_id, user_id, vk_id, admin_actor(admin_id, team_id)


def _event(*, team_id, vk_id, user_id, occurred_at, cost="1.0000", model_alias="claude-sonnet-4"):
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
        status=UsageStatus.SUCCESS,
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
        estimated_cost_usd=Decimal(cost),
    )


# ── P1-1 backfill ──


async def test_events_older_than_lookback_need_backfill(db_session, fixed_clock):
    """정상 주기 집계는 창 밖을 보지 않습니다. 이것이 backfill 이 필요한 이유입니다."""
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 8, 15, 3, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    await aggregate_usage_daily(db_session)
    assert (await db_session.execute(select(DailyUsageAggregate))).scalars().all() == []


async def test_backfill_picks_up_everything_from_first_event(db_session, fixed_clock):
    """M7 배포 시점에 이미 쌓여 있던 원천이 들어옵니다(리뷰 P1-1).

    구간을 주지 않으면 **원천의 가장 이른 이벤트**부터입니다.
    """
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    for moment in (
        datetime(2026, 7, 1, 3, 0, tzinfo=UTC),
        datetime(2026, 8, 15, 3, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
    ):
        db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=moment))
    await db_session.commit()

    assert await earliest_event_date(db_session) == date(2026, 7, 1)

    await run_backfill(since=None, until=None, dry_run=False)

    buckets = (
        await db_session.execute(
            select(DailyUsageAggregate.bucket_date).order_by(DailyUsageAggregate.bucket_date)
        )
    ).scalars().all()
    assert [b.isoformat() for b in buckets] == ["2026-07-01", "2026-08-15", "2026-10-01"]


async def test_backfill_is_idempotent_with_periodic_job(db_session, fixed_clock):
    """backfill 과 주기 집계가 같은 버킷을 건드려도 수치가 두 배가 되지 않습니다."""
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at))
    await db_session.commit()

    await aggregate_usage_daily(db_session)
    await run_backfill(since=date(2026, 9, 1), until=date(2026, 10, 2), dry_run=False)
    await aggregate_usage_daily(db_session)

    rows = (await db_session.execute(select(DailyUsageAggregate))).scalars().all()
    assert len(rows) == 1
    assert rows[0].request_count == 1


async def test_backfill_dry_run_writes_nothing(db_session, fixed_clock):
    team_id, user_id, vk_id, _ = await _fixtures(db_session)
    db_session.add(
        _event(
            team_id=team_id,
            vk_id=vk_id,
            user_id=user_id,
            occurred_at=datetime(2026, 7, 1, 3, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    days = await run_backfill(since=None, until=None, dry_run=True)

    assert days == (date(2026, 10, 2) - date(2026, 7, 1)).days + 1
    assert (await db_session.execute(select(DailyUsageAggregate))).scalars().all() == []


# ── P1-2 부분 월 trend ──


async def test_month_trend_respects_partial_month_range(db_session, fixed_clock):
    """`09-15 ~ 09-20` 요청에 9월 전체가 돌아오면 안 됩니다(리뷰 P1-2).

    기간 밖 사용량이 섞이면 overview·leaderboard 와 숫자가 달라져, 사용자가 건 필터를
    믿을 수 없게 됩니다.
    """
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    for day, cost in ((10, "5.0000"), (16, "1.0000"), (18, "2.0000"), (25, "7.0000")):
        db_session.add(
            _event(
                team_id=team_id,
                vk_id=vk_id,
                user_id=user_id,
                occurred_at=datetime(2026, 9, day, 3, 0, tzinfo=UTC),
                cost=cost,
            )
        )
    await db_session.commit()
    await run_backfill(since=date(2026, 9, 1), until=date(2026, 9, 30), dry_run=False)

    service = UsageService()
    trend = await service.trend(
        db_session,
        actor=actor,
        granularity=TrendGranularity.MONTH,
        from_date=date(2026, 9, 15),
        to_date=date(2026, 9, 20),
        requested=UsageFilter(),
    )

    assert [point.bucket for point in trend.points] == ["2026-09"]
    # 9/16 + 9/18 만. 9/10 과 9/25 는 기간 밖입니다.
    assert trend.points[0].totals.estimated_cost_usd == Decimal("3.000000")
    assert trend.points[0].totals.request_count == 2


async def test_month_trend_totals_match_overview(db_session, fixed_clock):
    """같은 기간이면 trend 합과 overview 합계가 같아야 합니다."""
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    for day in (16, 18, 25):
        db_session.add(
            _event(
                team_id=team_id,
                vk_id=vk_id,
                user_id=user_id,
                occurred_at=datetime(2026, 9, day, 3, 0, tzinfo=UTC),
                cost="2.0000",
            )
        )
    await db_session.commit()
    await run_backfill(since=date(2026, 9, 1), until=date(2026, 9, 30), dry_run=False)

    service = UsageService()
    window = {"from_date": date(2026, 9, 15), "to_date": date(2026, 9, 20)}

    trend = await service.trend(
        db_session,
        actor=actor,
        granularity=TrendGranularity.MONTH,
        requested=UsageFilter(),
        **window,
    )
    overview = await service.overview(
        db_session, actor=actor, requested=UsageFilter(), **window
    )

    trend_cost = sum(point.totals.estimated_cost_usd for point in trend.points)
    assert trend_cost == overview.totals.estimated_cost_usd == Decimal("4.000000")


async def test_month_trend_spans_year_boundary(db_session, fixed_clock):
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    for moment in (
        datetime(2026, 12, 20, 3, 0, tzinfo=UTC),
        datetime(2027, 1, 5, 3, 0, tzinfo=UTC),
    ):
        db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=moment))
    await db_session.commit()
    await run_backfill(since=date(2026, 12, 1), until=date(2027, 1, 31), dry_run=False)

    trend = await UsageService().trend(
        db_session,
        actor=actor,
        granularity=TrendGranularity.MONTH,
        from_date=date(2026, 12, 15),
        to_date=date(2027, 1, 10),
        requested=UsageFilter(),
    )
    assert [point.bucket for point in trend.points] == ["2026-12", "2027-01"]


# ── P2-2 필터 계약 ──


async def test_virtual_key_filter_applies_to_overview(db_session, fixed_clock):
    """문서가 공통 필터라고 정의한 것은 실제로 전 엔드포인트에서 동작해야 합니다."""
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    other_vk = await seed_virtual_key(
        db_session, team_id=team_id, owner_id=user_id, created_by=actor.user_id
    )
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, cost="1.0000"))
    db_session.add(
        _event(team_id=team_id, vk_id=other_vk, user_id=user_id, occurred_at=at, cost="9.0000")
    )
    await db_session.commit()
    await aggregate_usage_daily(db_session)

    overview = await UsageService().overview(
        db_session,
        actor=actor,
        from_date=date(2026, 10, 1),
        to_date=date(2026, 10, 2),
        requested=UsageFilter(virtual_key_id=vk_id),
    )
    assert overview.totals.estimated_cost_usd == Decimal("1.000000")


async def test_model_filter_applies_to_leaderboard(db_session, fixed_clock):
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    db_session.add(
        _event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, model_alias="a", cost="1")
    )
    db_session.add(
        _event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, model_alias="b", cost="9")
    )
    await db_session.commit()
    await aggregate_usage_daily(db_session)

    board = await UsageService().leaderboard(
        db_session,
        actor=actor,
        axis=UsageAxis.MODEL,
        metric=UsageMetric.COST,
        from_date=date(2026, 10, 1),
        to_date=date(2026, 10, 2),
        requested=UsageFilter(model_alias="a"),
        limit=10,
    )
    assert [item.key for item in board.items] == ["a"]


async def test_date_range_boundaries_are_inclusive(db_session, fixed_clock):
    """양끝 포함입니다. 끝 날짜의 하루가 통째로 빠지는 실수를 막습니다."""
    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    for day in (1, 2, 3):
        db_session.add(
            _event(
                team_id=team_id,
                vk_id=vk_id,
                user_id=user_id,
                occurred_at=datetime(2026, 10, day, 3, 0, tzinfo=UTC),
                cost="1.0000",
            )
        )
    await db_session.commit()
    await run_backfill(since=date(2026, 10, 1), until=date(2026, 10, 3), dry_run=False)

    totals = await UsageService().overview(
        db_session,
        actor=actor,
        from_date=date(2026, 10, 1),
        to_date=date(2026, 10, 3),
        requested=UsageFilter(),
    )
    assert totals.totals.request_count == 3

    narrowed = await UsageService().overview(
        db_session,
        actor=actor,
        from_date=date(2026, 10, 2),
        to_date=date(2026, 10, 2),
        requested=UsageFilter(),
    )
    assert narrowed.totals.request_count == 1


# ── P2-1 overview 스냅샷 일관성 ──


async def test_overview_totals_and_top_lists_share_one_snapshot(
    db_session, session_factory, fixed_clock, monkeypatch
):
    """합계를 읽은 뒤 집계 job 이 커밋돼도 상위 목록이 그것을 보면 안 됩니다(리뷰 P2-1).

    `READ COMMITTED` 에서는 SELECT 마다 새 스냅샷을 봅니다. 한 응답 안에서 카드마다 다른
    집계 결과를 보게 되므로, overview 트랜잭션만 `REPEATABLE READ` 로 올렸습니다.
    """
    from app.repositories.usage_repository import UsageQueryRepository

    team_id, user_id, vk_id, actor = await _fixtures(db_session)
    at = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    db_session.add(_event(team_id=team_id, vk_id=vk_id, user_id=user_id, occurred_at=at, cost="1.0000"))
    await db_session.commit()
    await aggregate_usage_daily(db_session)
    await db_session.commit()

    original = UsageQueryRepository.leaderboard
    injected = {"done": False}

    async def leaderboard_with_concurrent_commit(self, **kwargs):
        # 합계 조회와 첫 리더보드 조회 **사이**에 집계가 커밋되는 상황을 만듭니다.
        if not injected["done"]:
            injected["done"] = True
            async with session_factory() as other:
                other.add(
                    _event(
                        team_id=team_id,
                        vk_id=vk_id,
                        user_id=user_id,
                        occurred_at=at,
                        cost="99.0000",
                    )
                )
                await other.commit()
                await aggregate_usage_daily(other)
                await other.commit()
        return await original(self, **kwargs)

    monkeypatch.setattr(UsageQueryRepository, "leaderboard", leaderboard_with_concurrent_commit)

    overview = await UsageService().overview(
        db_session,
        actor=actor,
        from_date=date(2026, 10, 1),
        to_date=date(2026, 10, 2),
        requested=UsageFilter(),
    )

    assert injected["done"], "테스트가 동시 커밋을 실제로 끼워 넣지 못했습니다"
    team_cost = sum(item.totals.estimated_cost_usd for item in overview.top_teams)
    assert overview.totals.estimated_cost_usd == team_cost, (
        f"합계 {overview.totals.estimated_cost_usd} 와 상위 목록 합 {team_cost} 이 "
        "서로 다른 스냅샷을 봤습니다"
    )
    # 조회 시작 시점의 스냅샷이므로 끼어든 99 는 보이지 않습니다.
    assert overview.totals.estimated_cost_usd == Decimal("1.000000")
