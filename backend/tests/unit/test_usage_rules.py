"""사용량 집계·조회 규칙 테스트 (M7).

집계는 DB 없이 실행할 수 없으므로, 여기서 고정하는 것은 **DB 밖에서 결정되는 것**입니다.

- 버킷 경계가 예산과 같은 UTC 기준인 것
- 지표 정의(실패율, 총 토큰, 가중 평균)
- 인가 범위 축소 — 다른 팀·다른 사람은 빈 결과가 아니라 403
- 쿼리 모양 중 계약인 부분(`SUM(occurrence_count)`, 집계 UPSERT 의 충돌 키)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Date, func, literal
from sqlalchemy.dialects import postgresql

from app.core.auth import CurrentAdmin
from app.core.exceptions import ForbiddenError, ValidationError
from app.jobs.usage_jobs import _day_bounds, _grouped_select, _upsert
from app.models.enums import UserRole
from app.models.usage import DailyUsageAggregate, MonthlyUsageAggregate, UsageEvent
from app.policy import budget as budget_policy
from app.policy import usage as policy
from app.policy.usage import NO_USER_ID
from app.repositories.usage_repository import UsageFilter, auth_event_summary_query
from app.services.usage_service import MAX_RANGE_DAYS, UsageService

KST = timezone(timedelta(hours=9))

TEAM_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
TEAM_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_A = uuid.UUID("33333333-3333-3333-3333-333333333333")
USER_B = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _actor(role: UserRole, *, team_id=TEAM_A, user_id=USER_A) -> CurrentAdmin:
    return CurrentAdmin(user_id=user_id, email="x@example.com", role=role, team_id=team_id)


# ── 버킷 경계 ──


def test_month_boundary_is_shared_with_budget():
    """예산과 **같은 함수**를 씁니다. 두 벌로 두면 한쪽이 바뀔 때 조용히 갈라집니다."""
    assert policy.period_bounds_utc is budget_policy.period_bounds


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # KST 로는 10월 1일이지만 UTC 로는 9월 30일. 일 버킷도 월 경계와 같은 기준입니다.
        (datetime(2026, 10, 1, 0, 30, tzinfo=KST), date(2026, 9, 30)),
        (datetime(2026, 10, 1, 9, 0, tzinfo=KST), date(2026, 10, 1)),
        (datetime(2026, 9, 15, 12, 0, tzinfo=UTC), date(2026, 9, 15)),
    ],
)
def test_utc_date_bucket(moment, expected):
    assert policy.utc_date(moment) == expected


def test_months_in_range_crosses_year():
    assert policy.months_in_range(date(2026, 11, 28), date(2027, 1, 2)) == [
        "2026-11",
        "2026-12",
        "2027-01",
    ]


def test_months_in_range_single_month():
    assert policy.months_in_range(date(2026, 9, 3), date(2026, 9, 20)) == ["2026-09"]


def test_aggregation_window_looks_back():
    """늦게 도착하는 이벤트 때문에 최신 버킷만 갱신하지 않습니다."""
    now = datetime(2026, 9, 10, 5, 0, tzinfo=UTC)
    assert policy.aggregation_window(now, 3) == (date(2026, 9, 7), date(2026, 9, 10))


def test_aggregation_window_zero_lookback_is_today_only():
    now = datetime(2026, 9, 10, 5, 0, tzinfo=UTC)
    assert policy.aggregation_window(now, 0) == (date(2026, 9, 10), date(2026, 9, 10))


def test_day_bounds_includes_end_date():
    """종료 일자는 **포함**입니다. 그 하루가 통째로 빠지는 실수를 막습니다."""
    start, end = _day_bounds(date(2026, 9, 7), date(2026, 9, 10))
    assert start == datetime(2026, 9, 7, tzinfo=UTC)
    assert end == datetime(2026, 9, 11, tzinfo=UTC)


# ── 지표 정의 ──


def test_total_tokens_excludes_cache_tokens():
    """캐시 토큰은 단가가 달라 합산하면 '토큰 수'의 의미가 흐려집니다."""
    assert policy.total_tokens(100, 50) == 150


@pytest.mark.parametrize(
    ("requests", "errors", "expected"),
    [
        (0, 0, "0.00"),
        (100, 0, "0.00"),
        (100, 7, "7.00"),
        (3, 1, "33.33"),
        (100, 100, "100.00"),
    ],
)
def test_failure_rate(requests, errors, expected):
    assert policy.failure_rate(requests, errors) == Decimal(expected)


def test_failure_rate_of_zero_requests_is_zero_not_hundred():
    """0/0 을 100% 로 보이게 하면 트래픽이 없는 팀이 전부 장애로 보입니다."""
    assert policy.failure_rate(0, 0) == Decimal("0.00")


def test_weighted_average_respects_volume():
    """호출 3건인 날과 3만 건인 날이 같은 무게를 가지면 안 됩니다."""
    assert policy.weighted_average([(1000, 3), (100, 30000)]) == 100
    assert policy.weighted_average([]) == 0
    assert policy.weighted_average([(500, 0)]) == 0


def test_no_user_sentinel_is_nil_uuid():
    """사람 계정과 섞이지 않도록 예약값을 씁니다(07 미결정 #5 종결)."""
    assert str(NO_USER_ID) == "00000000-0000-0000-0000-000000000000"
    assert NO_USER_ID != USER_A


# ── 인가 범위 축소 ──


async def test_admin_filters_pass_through():
    requested = UsageFilter(team_id=TEAM_B, user_id=USER_B)
    scoped = await UsageService()._scoped_filters(None, _actor(UserRole.ADMIN), requested)
    assert scoped is requested


async def test_leader_is_narrowed_to_own_team():
    scoped = await UsageService()._scoped_filters(
        None, _actor(UserRole.TEAM_LEADER), UsageFilter()
    )
    assert scoped.team_id == TEAM_A
    assert scoped.user_id is None


async def test_leader_cannot_query_other_team():
    """빈 결과가 아니라 403 입니다. 빈 결과면 '없다'와 '못 본다'를 구분할 수 없습니다."""
    with pytest.raises(ForbiddenError):
        await UsageService()._scoped_filters(
            None, _actor(UserRole.TEAM_LEADER), UsageFilter(team_id=TEAM_B)
        )


async def test_member_is_narrowed_to_self():
    scoped = await UsageService()._scoped_filters(None, _actor(UserRole.MEMBER), UsageFilter())
    assert scoped.team_id == TEAM_A
    assert scoped.user_id == USER_A


async def test_member_cannot_query_other_user():
    with pytest.raises(ForbiddenError):
        await UsageService()._scoped_filters(
            None, _actor(UserRole.MEMBER), UsageFilter(user_id=USER_B)
        )


async def test_teamless_non_admin_is_rejected():
    with pytest.raises(ForbiddenError):
        await UsageService()._scoped_filters(
            None, _actor(UserRole.MEMBER, team_id=None), UsageFilter()
        )


def test_inverted_date_range_is_rejected():
    with pytest.raises(ValidationError) as exc:
        UsageService()._validate_range(date(2026, 9, 10), date(2026, 9, 1))
    assert exc.value.code == "invalid_date_range"


def test_too_wide_date_range_is_rejected():
    """집계 테이블이라도 무한 범위는 스캔 비용이 무제한입니다."""
    start = date(2026, 1, 1)
    with pytest.raises(ValidationError) as exc:
        UsageService()._validate_range(start, start + timedelta(days=MAX_RANGE_DAYS + 1))
    assert exc.value.code == "date_range_too_wide"

    UsageService()._validate_range(start, start + timedelta(days=MAX_RANGE_DAYS))


# ── 쿼리 모양 (DB 없이 고정할 수 있는 계약) ──


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _daily_upsert_sql() -> str:
    bucket = func.date(func.timezone("UTC", UsageEvent.occurred_at)).cast(Date).label("bucket_date")
    start, end = _day_bounds(date(2026, 9, 1), date(2026, 9, 3))
    return _sql(_upsert(DailyUsageAggregate, "bucket_date", _grouped_select(bucket, start, end)))


def test_aggregation_is_idempotent_upsert():
    """집계는 워터마크 없이 같은 구간을 다시 돌 수 있어야 합니다. 그래서 UPSERT 입니다."""
    sql = _daily_upsert_sql()
    assert "ON CONFLICT (bucket_date, team_id, user_id, virtual_key_id, model_alias) DO UPDATE" in sql
    assert "estimated_cost_usd = excluded.estimated_cost_usd" in sql


def test_aggregation_maps_null_user_to_sentinel():
    """집계 PK 는 NULL 을 담을 수 없어 `TEAM` 소유 VK 호출을 예약 UUID 로 모읍니다."""
    sql = _daily_upsert_sql()
    assert f"coalesce(usage.usage_events.user_id, '{NO_USER_ID}')" in sql


def test_aggregation_counts_timeout_as_error():
    """ERROR 와 TIMEOUT 은 운영 관점에서 둘 다 실패한 호출입니다."""
    sql = _daily_upsert_sql()
    assert "FILTER (WHERE usage.usage_events.status != 'SUCCESS')" in sql


def test_monthly_aggregation_reads_source_not_daily():
    """일별 p95 의 p95 는 그 달의 p95 가 아니라서, 월 집계도 원천에서 계산합니다."""
    start, end = policy.period_bounds_utc("2026-09")
    sql = _sql(
        _upsert(
            MonthlyUsageAggregate,
            "period",
            _grouped_select(literal("2026-09").label("period"), start, end),
        )
    )
    assert "FROM usage.usage_events" in sql
    assert "daily_usage_aggregates" not in sql
    assert "percentile_disc(0.95)" in sql


def test_auth_event_summary_sums_occurrence_count():
    """행 수로 세면 실패가 과소 계상됩니다 — gateway 가 60초 창으로 묶어 기록합니다(09 문서)."""
    sql = _sql(auth_event_summary_query(date(2026, 9, 1), date(2026, 9, 30), UsageFilter()))
    assert "coalesce(sum(usage.auth_events.occurrence_count), 0)" in sql
    assert "GROUP BY usage.auth_events.outcome" in sql


def test_auth_event_summary_applies_scope_filters():
    """인가에서 좁힌 범위가 쿼리까지 내려가는지 봅니다."""
    sql = _sql(
        auth_event_summary_query(
            date(2026, 9, 1), date(2026, 9, 30), UsageFilter(team_id=TEAM_A, user_id=USER_A)
        )
    )
    assert f"usage.auth_events.team_id = '{TEAM_A}'" in sql
    assert f"usage.auth_events.user_id = '{USER_A}'" in sql
