"""사용량 조회.

읽기 전용입니다. 쓰기는 집계 job(`app.jobs.usage_jobs`)이 하고, 원천은 gateway 가 씁니다.
그래서 이 서비스에는 트랜잭션도 캐시 무효화도 없습니다.

하는 일은 두 가지입니다.

1. **인가 범위로 조회 조건을 좁히는 것** — ADMIN 전체 / 팀장 자기 팀 / MEMBER 자기 자신
   (00 문서 인가 표). router 의존성만으로는 끝나지 않아 여기서 다시 확인합니다.
2. **지표를 한 정의로 계산하는 것** — 실패율·총 토큰 같은 파생값을 프론트가 중복 구현하면
   화면마다 숫자가 갈립니다.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentAdmin
from app.core.exceptions import ForbiddenError, ValidationError
from app.models.enums import UserRole
from app.policy import usage as policy
from app.policy.usage import (
    NO_USER_ID,
    NO_USER_LABEL,
    TrendGranularity,
    UsageAxis,
    UsageMetric,
)
from app.repositories.team_repository import TeamRepository
from app.repositories.usage_repository import (
    AggregateTotals,
    UsageFilter,
    UsageQueryRepository,
    UsageRankRow,
)
from app.repositories.user_repository import UserRepository
from app.repositories.virtual_key_repository import VirtualKeyRepository
from app.schemas.usage import (
    AuthEventSummaryItem,
    AuthEventSummaryResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    UsageOverviewResponse,
    UsageTotals,
    UsageTrendPoint,
    UsageTrendResponse,
)

logger = structlog.get_logger()

#: 한 번에 조회할 수 있는 최대 기간(일). 집계 테이블이라도 무한 범위는 스캔 비용이 무제한입니다.
MAX_RANGE_DAYS = 366
#: overview 의 top N. 화면 카드가 담을 수 있는 크기입니다.
TOP_N = 5


class UsageService:
    async def overview(
        self,
        session: AsyncSession,
        *,
        actor: CurrentAdmin,
        from_date: date,
        to_date: date,
        requested: UsageFilter,
    ) -> UsageOverviewResponse:
        """대시보드 overview — 합계 + 상위 팀/사용자/모델.

        네 번의 조회를 한 응답으로 묶습니다. 화면이 카드마다 따로 호출하면 카드 사이에
        집계 job 이 돌아 숫자가 서로 맞지 않을 수 있습니다.
        """
        self._validate_range(from_date, to_date)
        filters = await self._scoped_filters(session, actor, requested)
        repo = UsageQueryRepository(session)

        totals = await repo.totals(start=from_date, end=to_date, filters=filters)
        top = {}
        for axis in (UsageAxis.TEAM, UsageAxis.USER, UsageAxis.MODEL):
            rows = await repo.leaderboard(
                axis=axis,
                metric=UsageMetric.COST,
                start=from_date,
                end=to_date,
                filters=filters,
                limit=TOP_N,
            )
            top[axis] = await self._to_entries(session, axis, rows)

        return UsageOverviewResponse(
            from_date=from_date,
            to_date=to_date,
            totals=_to_totals(totals),
            top_teams=top[UsageAxis.TEAM],
            top_users=top[UsageAxis.USER],
            top_models=top[UsageAxis.MODEL],
        )

    async def leaderboard(
        self,
        session: AsyncSession,
        *,
        actor: CurrentAdmin,
        axis: UsageAxis,
        metric: UsageMetric,
        from_date: date,
        to_date: date,
        requested: UsageFilter,
        limit: int,
    ) -> LeaderboardResponse:
        self._validate_range(from_date, to_date)
        filters = await self._scoped_filters(session, actor, requested)

        rows = await UsageQueryRepository(session).leaderboard(
            axis=axis,
            metric=metric,
            start=from_date,
            end=to_date,
            filters=filters,
            limit=limit,
        )
        return LeaderboardResponse(
            axis=axis,
            metric=metric,
            from_date=from_date,
            to_date=to_date,
            items=await self._to_entries(session, axis, rows),
        )

    async def trend(
        self,
        session: AsyncSession,
        *,
        actor: CurrentAdmin,
        granularity: TrendGranularity,
        from_date: date,
        to_date: date,
        requested: UsageFilter,
    ) -> UsageTrendResponse:
        self._validate_range(from_date, to_date)
        filters = await self._scoped_filters(session, actor, requested)

        rows = await UsageQueryRepository(session).trend(
            start=from_date, end=to_date, filters=filters, granularity=granularity
        )
        return UsageTrendResponse(
            granularity=granularity,
            from_date=from_date,
            to_date=to_date,
            points=[UsageTrendPoint(bucket=row.bucket, totals=_to_totals(row.totals)) for row in rows],
        )

    async def auth_events(
        self,
        session: AsyncSession,
        *,
        actor: CurrentAdmin,
        from_date: date,
        to_date: date,
        requested: UsageFilter,
    ) -> AuthEventSummaryResponse:
        """정책 거절 요약. 성공 호출과 분리된 테이블에서 읽습니다(01 문서)."""
        self._validate_range(from_date, to_date)
        filters = await self._scoped_filters(session, actor, requested)

        rows = await UsageQueryRepository(session).auth_events(
            start=from_date, end=to_date, filters=filters
        )
        return AuthEventSummaryResponse(
            from_date=from_date,
            to_date=to_date,
            total_occurrences=sum(row.occurrence_count for row in rows),
            items=[
                AuthEventSummaryItem(
                    outcome=row.outcome,
                    occurrence_count=row.occurrence_count,
                    event_rows=row.distinct_rows,
                )
                for row in rows
            ],
        )

    # ── 내부 ──

    @staticmethod
    def _validate_range(from_date: date, to_date: date) -> None:
        if from_date > to_date:
            raise ValidationError("from_date 가 to_date 보다 뒤입니다", code="invalid_date_range")
        if (to_date - from_date) > timedelta(days=MAX_RANGE_DAYS):
            raise ValidationError(
                f"조회 기간은 최대 {MAX_RANGE_DAYS}일입니다",
                code="date_range_too_wide",
                details={"max_days": MAX_RANGE_DAYS},
            )

    async def _scoped_filters(
        self, session: AsyncSession, actor: CurrentAdmin, requested: UsageFilter
    ) -> UsageFilter:
        """인가 범위로 조회 조건을 좁힙니다.

        다른 팀·다른 사람을 지정하면 빈 결과가 아니라 **403** 입니다. 빈 결과로 돌려주면
        "데이터가 없다"와 "볼 권한이 없다"를 구분할 수 없습니다(00 문서).
        """
        if actor.is_admin:
            return requested

        own_team = actor.team_id
        if own_team is None:
            raise ForbiddenError("팀에 소속되지 않은 사용자는 사용량을 조회할 수 없습니다")
        if requested.team_id is not None and requested.team_id != own_team:
            raise ForbiddenError("다른 팀의 사용량은 조회할 수 없습니다")

        if actor.role == UserRole.TEAM_LEADER:
            if requested.user_id is not None:
                await self._require_same_team(session, requested.user_id, own_team)
            return UsageFilter(
                team_id=own_team,
                user_id=requested.user_id,
                virtual_key_id=requested.virtual_key_id,
                model_alias=requested.model_alias,
            )

        # MEMBER — 자기 자신만. 팀 공용 VK 호출은 사람에 귀속되지 않아 여기에 보이지 않습니다.
        if requested.user_id is not None and requested.user_id != actor.user_id:
            raise ForbiddenError("다른 사용자의 사용량은 조회할 수 없습니다")
        return UsageFilter(
            team_id=own_team,
            user_id=actor.user_id,
            virtual_key_id=requested.virtual_key_id,
            model_alias=requested.model_alias,
        )

    @staticmethod
    async def _require_same_team(
        session: AsyncSession, user_id: uuid.UUID, team_id: uuid.UUID
    ) -> None:
        user = await UserRepository(session).get(user_id)
        if user is None or user.team_id != team_id:
            raise ForbiddenError("다른 팀 사용자의 사용량은 조회할 수 없습니다")

    async def _to_entries(
        self, session: AsyncSession, axis: UsageAxis, rows: list[UsageRankRow]
    ) -> list[LeaderboardEntry]:
        names = await self._resolve_names(session, axis, [row.key for row in rows])
        return [
            LeaderboardEntry(key=row.key, name=names.get(row.key), totals=_to_totals(row.totals))
            for row in rows
        ]

    @staticmethod
    async def _resolve_names(
        session: AsyncSession, axis: UsageAxis, keys: list[str]
    ) -> dict[str, str]:
        """축 식별자 → 표시 이름. UUID 만 늘어선 리더보드는 읽을 수 없습니다."""
        if not keys:
            return {}
        if axis == UsageAxis.MODEL:
            # alias 자체가 이름입니다.
            return {key: key for key in keys}

        ids = [uuid.UUID(key) for key in keys]
        if axis == UsageAxis.TEAM:
            resolved = await TeamRepository(session).names_for(ids)
        elif axis == UsageAxis.VIRTUAL_KEY:
            resolved = await VirtualKeyRepository(session).names_for(ids)
        else:
            resolved = await UserRepository(session).names_for(ids)
            # 사람에 귀속되지 않는 호출(TEAM 소유 VK)은 이름 대신 라벨을 답니다. 비워 두면
            # 비용이 실린 행이 이름 없는 행으로 남아 읽는 사람이 원인을 못 찾습니다.
            resolved[NO_USER_ID] = NO_USER_LABEL

        return {str(key): name for key, name in resolved.items()}


def _to_totals(totals: AggregateTotals) -> UsageTotals:
    return UsageTotals(
        request_count=totals.request_count,
        success_count=totals.success_count,
        error_count=totals.error_count,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        total_tokens=policy.total_tokens(totals.input_tokens, totals.output_tokens),
        cache_write_tokens=totals.cache_write_tokens,
        cache_read_tokens=totals.cache_read_tokens,
        estimated_cost_usd=totals.estimated_cost_usd,
        failure_rate_pct=policy.failure_rate(totals.request_count, totals.error_count),
        avg_latency_ms=totals.avg_latency_ms,
    )
