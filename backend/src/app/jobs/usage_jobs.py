"""사용량 집계.

`usage.usage_events`(gateway 가 씀) → 일/월 집계 테이블(backend 가 씀). 원천을 읽고 집계를
쓰는 이 방향만 있습니다. 대시보드와 리더보드는 **집계 테이블만** 읽습니다(01 문서).

두 작업 모두 **멱등**합니다. 같은 구간을 다시 돌려도 UPSERT 로 덮어쓰므로 결과가 같습니다.
그래서 실패하면 그냥 다음 주기에 다시 돌면 되고, 워터마크 상태를 따로 들고 있지 않습니다.
상태를 들고 있으면 그 상태 자체가 틀어질 때 복구 수단이 없어집니다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import Date, Integer, Uuid, and_, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.clock import utcnow
from app.core.config import get_settings
from app.models.enums import UsageStatus
from app.models.usage import DailyUsageAggregate, MonthlyUsageAggregate, UsageEvent
from app.policy.usage import NO_USER_ID, aggregation_window, months_in_range, period_bounds_utc

logger = structlog.get_logger()

#: 집계 대상 축. 집계 테이블 PK 의 뒤쪽 네 컬럼입니다.
_AXIS_COLUMNS = ("team_id", "user_id", "virtual_key_id", "model_alias")

#: 갱신 대상 지표. PK 를 제외한 전부입니다.
_METRIC_COLUMNS = (
    "request_count",
    "success_count",
    "error_count",
    "input_tokens",
    "output_tokens",
    "cache_write_tokens",
    "cache_read_tokens",
    "estimated_cost_usd",
    "avg_latency_ms",
    "p95_latency_ms",
    "aggregated_at",
)


def _metric_expressions() -> list:
    """지표 계산식. 일·월이 **같은 식**을 씁니다 — 갈리면 두 화면의 숫자가 달라집니다."""
    return [
        func.count().label("request_count"),
        func.count().filter(UsageEvent.status == UsageStatus.SUCCESS).label("success_count"),
        # ERROR 와 TIMEOUT 을 함께 셉니다. 운영 관점에서는 둘 다 실패한 호출입니다.
        func.count().filter(UsageEvent.status != UsageStatus.SUCCESS).label("error_count"),
        func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(UsageEvent.cache_write_tokens), 0).label("cache_write_tokens"),
        func.coalesce(func.sum(UsageEvent.cache_read_tokens), 0).label("cache_read_tokens"),
        func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0).label("estimated_cost_usd"),
        func.coalesce(func.round(func.avg(UsageEvent.latency_ms)), 0)
        .cast(Integer)
        .label("avg_latency_ms"),
        func.coalesce(
            func.percentile_disc(0.95).within_group(UsageEvent.latency_ms), 0
        )
        .cast(Integer)
        .label("p95_latency_ms"),
        func.now().label("aggregated_at"),
    ]


def _axis_expressions() -> list:
    return [
        UsageEvent.team_id.label("team_id"),
        # `TEAM` 소유 VK 호출은 사람에 귀속되지 않아 원천이 NULL 입니다. 집계 PK 는 NULL 을
        # 담을 수 없으므로 예약 UUID 로 모읍니다(07 미결정 #5 종결).
        func.coalesce(UsageEvent.user_id, literal(NO_USER_ID, Uuid)).label("user_id"),
        UsageEvent.virtual_key_id.label("virtual_key_id"),
        UsageEvent.model_alias.label("model_alias"),
    ]


def _grouped_select(bucket_expr, start: datetime, end: datetime) -> Select:
    axes = _axis_expressions()
    return (
        select(bucket_expr, *axes, *_metric_expressions())
        .where(and_(UsageEvent.occurred_at >= start, UsageEvent.occurred_at < end))
        .group_by(bucket_expr, *axes)
    )


def _upsert(table, bucket_column: str, source: Select):
    columns = [bucket_column, *_AXIS_COLUMNS, *_METRIC_COLUMNS]
    stmt = pg_insert(table).from_select(columns, source)
    return stmt.on_conflict_do_update(
        index_elements=[bucket_column, *_AXIS_COLUMNS],
        set_={name: getattr(stmt.excluded, name) for name in _METRIC_COLUMNS},
    )


async def aggregate_usage_daily(session: AsyncSession) -> int:
    """최근 구간의 일 집계를 다시 만듭니다. 처리한 버킷 수를 돌려줍니다.

    되돌아보는 일수(`USAGE_AGGREGATION_LOOKBACK_DAYS`)만큼 재집계합니다. 늦게 도착한
    이벤트가 영원히 집계에 빠지는 것을 막기 위해서입니다(gateway 의 메모리 스풀).
    """
    settings = get_settings()
    start_date, end_date = aggregation_window(utcnow(), settings.USAGE_AGGREGATION_LOOKBACK_DAYS)
    start, end = _day_bounds(start_date, end_date)

    bucket = func.date(func.timezone("UTC", UsageEvent.occurred_at)).cast(Date).label("bucket_date")
    result = await session.execute(
        _upsert(DailyUsageAggregate, "bucket_date", _grouped_select(bucket, start, end))
    )
    await session.commit()

    count = result.rowcount or 0
    logger.info(
        "job.usage_daily_aggregated",
        rows=count,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )
    return count


async def aggregate_usage_monthly(session: AsyncSession) -> int:
    """재집계 구간이 걸치는 월의 월 집계를 다시 만듭니다.

    **일 집계가 아니라 원천에서 직접 계산합니다.** 05 문서의 작업 표는 "일 집계 → 월 집계"로
    적혀 있지만, `p95_latency_ms` 는 합성할 수 없는 지표입니다 — 일별 p95 의 p95 는 그 달의
    p95 가 아닙니다. 합계 지표만 롤업하고 지연 분포만 원천에서 읽으면 코드 경로가 둘로
    갈라지므로, 한 경로로 두고 구간을 월 단위로 좁혔습니다.
    """
    settings = get_settings()
    start_date, end_date = aggregation_window(utcnow(), settings.USAGE_AGGREGATION_LOOKBACK_DAYS)

    total = 0
    for period in months_in_range(start_date, end_date):
        start, end = period_bounds_utc(period)
        source = _grouped_select(literal(period).label("period"), start, end)
        result = await session.execute(_upsert(MonthlyUsageAggregate, "period", source))
        total += result.rowcount or 0

    await session.commit()
    logger.info("job.usage_monthly_aggregated", rows=total, months=months_in_range(start_date, end_date))
    return total


def _day_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """`[start, end]` 일자를 timestamptz 반개구간으로. 끝 날짜의 하루를 포함합니다."""
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return start, end
