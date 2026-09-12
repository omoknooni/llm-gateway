"""사용량 집계 조회.

원천(`usage.usage_events`)이 아니라 **집계 테이블**을 읽습니다. 원천을 스캔하면 이벤트가
쌓일수록 조회가 느려지고, 같은 숫자를 대시보드와 리더보드가 다르게 계산하게 됩니다
(01 문서 / leaderboard-and-dashboard.md).

`p95_latency_ms` 는 버킷 단위로만 의미가 있습니다. 여러 버킷을 합칠 때 이 값을 다시 평균내지
않습니다 — p95 의 p95 는 p95 가 아닙니다. 기간 합계 응답에는 가중 평균 지연만 싣습니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import AuthEvent, DailyUsageAggregate, MonthlyUsageAggregate
from app.policy.usage import TrendGranularity, UsageAxis, UsageMetric


@dataclass(frozen=True)
class UsageFilter:
    """조회 범위. 인가에서 좁힌 값도 여기로 들어옵니다(팀장 → 자기 팀)."""

    team_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    virtual_key_id: uuid.UUID | None = None
    model_alias: str | None = None


@dataclass(frozen=True)
class AggregateTotals:
    request_count: int
    success_count: int
    error_count: int
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: Decimal
    avg_latency_ms: int


@dataclass(frozen=True)
class UsageRankRow:
    key: str
    totals: AggregateTotals


@dataclass(frozen=True)
class UsageTrendRow:
    bucket: str
    totals: AggregateTotals


@dataclass(frozen=True)
class AuthEventRow:
    outcome: str
    occurrence_count: int
    distinct_rows: int


_AXIS_COLUMN = {
    UsageAxis.TEAM: "team_id",
    UsageAxis.USER: "user_id",
    UsageAxis.VIRTUAL_KEY: "virtual_key_id",
    UsageAxis.MODEL: "model_alias",
}


def _sum(column) -> ColumnElement:
    return func.coalesce(func.sum(column), 0)


def _weighted_latency(table) -> ColumnElement:
    """호출 수로 가중한 평균 지연.

    버킷별 평균을 단순 평균하면 호출이 3건인 날과 3만 건인 날이 같은 무게를 갖습니다.
    """
    weighted = func.sum(table.avg_latency_ms * table.request_count)
    return func.coalesce(weighted / func.nullif(func.sum(table.request_count), 0), 0)


def _total_columns(table) -> list[ColumnElement]:
    return [
        _sum(table.request_count),
        _sum(table.success_count),
        _sum(table.error_count),
        _sum(table.input_tokens),
        _sum(table.output_tokens),
        _sum(table.cache_write_tokens),
        _sum(table.cache_read_tokens),
        _sum(table.estimated_cost_usd),
        _weighted_latency(table),
    ]


def _to_totals(row, offset: int = 0) -> AggregateTotals:
    return AggregateTotals(
        request_count=int(row[offset]),
        success_count=int(row[offset + 1]),
        error_count=int(row[offset + 2]),
        input_tokens=int(row[offset + 3]),
        output_tokens=int(row[offset + 4]),
        cache_write_tokens=int(row[offset + 5]),
        cache_read_tokens=int(row[offset + 6]),
        estimated_cost_usd=Decimal(row[offset + 7]),
        avg_latency_ms=int(row[offset + 8]),
    )


def _metric_order(table, metric: UsageMetric) -> ColumnElement:
    if metric == UsageMetric.REQUESTS:
        return _sum(table.request_count).desc()
    if metric == UsageMetric.TOKENS:
        return (_sum(table.input_tokens) + _sum(table.output_tokens)).desc()
    return _sum(table.estimated_cost_usd).desc()


def auth_event_summary_query(start: date, end: date, filters: UsageFilter) -> Select:
    """정책 거절 요약 쿼리.

    **행 수가 아니라 `SUM(occurrence_count)`** 를 씁니다. gateway 가 동일 출처의 연속 실패를
    60초 창으로 묶어 한 행에 기록하고, 그 창이 프로세스 로컬이라 pod 수만큼 행이 나뉘기
    때문입니다(01·09 문서). 행 수로 세면 실패가 과소 계상됩니다.

    세션 없이 만들 수 있게 모듈 함수로 둡니다 — 이 규칙은 SQL 모양 자체가 계약이라
    렌더링해서 테스트합니다.
    """
    occurrences = func.coalesce(func.sum(AuthEvent.occurrence_count), 0)
    bucket = func.date(func.timezone("UTC", AuthEvent.occurred_at))

    stmt = select(AuthEvent.outcome, occurrences, func.count()).where(
        bucket >= start, bucket <= end
    )
    if filters.team_id is not None:
        stmt = stmt.where(AuthEvent.team_id == filters.team_id)
    if filters.user_id is not None:
        stmt = stmt.where(AuthEvent.user_id == filters.user_id)
    if filters.virtual_key_id is not None:
        stmt = stmt.where(AuthEvent.virtual_key_id == filters.virtual_key_id)
    if filters.model_alias is not None:
        stmt = stmt.where(AuthEvent.model_alias == filters.model_alias)

    return stmt.group_by(AuthEvent.outcome).order_by(occurrences.desc())


class UsageQueryRepository:
    """일/월 집계 테이블 조회. 두 테이블의 지표 컬럼이 같아 한 클래스로 다룹니다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def totals(
        self, *, start: date, end: date, filters: UsageFilter
    ) -> AggregateTotals:
        stmt = self._scoped(select(*_total_columns(DailyUsageAggregate)), start, end, filters)
        row = (await self._session.execute(stmt)).one()
        return _to_totals(row)

    async def leaderboard(
        self,
        *,
        axis: UsageAxis,
        metric: UsageMetric,
        start: date,
        end: date,
        filters: UsageFilter,
        limit: int,
    ) -> list[UsageRankRow]:
        key_column = getattr(DailyUsageAggregate, _AXIS_COLUMN[axis])
        stmt = self._scoped(
            select(key_column, *_total_columns(DailyUsageAggregate)), start, end, filters
        )
        stmt = (
            stmt.group_by(key_column)
            .order_by(_metric_order(DailyUsageAggregate, metric))
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [UsageRankRow(key=str(row[0]), totals=_to_totals(row, offset=1)) for row in rows]

    async def trend(
        self,
        *,
        start: date,
        end: date,
        filters: UsageFilter,
        granularity: TrendGranularity,
    ) -> list[UsageTrendRow]:
        """기간별 추이.

        **월 단위도 일 집계에서 만듭니다.** 월 집계 테이블을 쓰면 `2026-09-15 ~ 2026-09-20`
        요청에 9월 **전체**가 돌아옵니다 — 같은 화면의 overview·leaderboard 와 숫자가
        달라지고, 사용자가 건 기간 필터를 믿을 수 없게 됩니다.

        추이 응답에는 p95 를 싣지 않으므로(합성 불가) 일 집계의 합계와 가중 평균만으로
        정확하게 만들 수 있습니다. 월 집계 테이블은 **월 전체가 곧 기간**인 곳
        (예산 breakdown)에서만 씁니다.
        """
        bucket = (
            func.to_char(DailyUsageAggregate.bucket_date, "YYYY-MM")
            if granularity == TrendGranularity.MONTH
            else DailyUsageAggregate.bucket_date
        )
        stmt = self._scoped(select(bucket, *_total_columns(DailyUsageAggregate)), start, end, filters)
        stmt = stmt.group_by(bucket).order_by(bucket)
        rows = (await self._session.execute(stmt)).all()
        return [
            UsageTrendRow(
                bucket=row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                totals=_to_totals(row, offset=1),
            )
            for row in rows
        ]

    async def auth_events(
        self, *, start: date, end: date, filters: UsageFilter
    ) -> list[AuthEventRow]:
        rows = (await self._session.execute(auth_event_summary_query(start, end, filters))).all()
        return [
            AuthEventRow(outcome=row[0], occurrence_count=int(row[1]), distinct_rows=int(row[2]))
            for row in rows
        ]

    # ── 내부 ──

    def _scoped(self, stmt: Select, start: date, end: date, filters: UsageFilter) -> Select:
        stmt = stmt.where(
            DailyUsageAggregate.bucket_date >= start, DailyUsageAggregate.bucket_date <= end
        )
        return self._apply_filters(stmt, DailyUsageAggregate, filters)

    @staticmethod
    def _apply_filters(stmt: Select, table, filters: UsageFilter) -> Select:
        if filters.team_id is not None:
            stmt = stmt.where(table.team_id == filters.team_id)
        if filters.user_id is not None:
            stmt = stmt.where(table.user_id == filters.user_id)
        if filters.virtual_key_id is not None:
            stmt = stmt.where(table.virtual_key_id == filters.virtual_key_id)
        if filters.model_alias is not None:
            stmt = stmt.where(table.model_alias == filters.model_alias)
        return stmt


@dataclass(frozen=True)
class UsageBreakdownRow:
    key: str
    cost_usd: Decimal
    request_count: int
    input_tokens: int
    output_tokens: int


_COST = func.coalesce(func.sum(MonthlyUsageAggregate.estimated_cost_usd), 0)
_REQUESTS = func.coalesce(func.sum(MonthlyUsageAggregate.request_count), 0)
_INPUT = func.coalesce(func.sum(MonthlyUsageAggregate.input_tokens), 0)
_OUTPUT = func.coalesce(func.sum(MonthlyUsageAggregate.output_tokens), 0)


def _to_rows(result) -> list[UsageBreakdownRow]:
    return [
        UsageBreakdownRow(
            key=str(key),
            cost_usd=Decimal(cost),
            request_count=int(requests),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
        )
        for key, cost, requests, input_tokens, output_tokens in result
    ]


class UsageAggregateRepository:
    """예산 화면의 breakdown 전용(M6). 월 집계를 축별로 접습니다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def team_breakdown_by_user(self, team_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.user_id, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.team_id == team_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.user_id)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))

    async def team_breakdown_by_model(self, team_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.model_alias, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.team_id == team_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.model_alias)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))

    async def user_breakdown_by_model(self, user_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.model_alias, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.user_id == user_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.model_alias)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))
