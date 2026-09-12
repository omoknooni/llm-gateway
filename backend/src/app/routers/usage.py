"""사용량·비용 조회.

집계 테이블만 읽습니다. 원천(`usage.usage_events`)을 직접 훑는 엔드포인트를 두지 않습니다 —
이벤트가 쌓일수록 느려지고, 대시보드와 리더보드가 다른 숫자를 계산하게 됩니다(01 문서).

인가는 `AdminDep` 로 인증만 확인하고, **범위 축소는 서비스가 합니다.** 팀장이 자기 팀으로,
MEMBER 가 자기 자신으로 좁혀지는 판정에 팀 소속 조회가 필요해 의존성만으로는 끝나지
않습니다(00 문서 인가 표).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.core.auth import AdminDep
from app.core.clock import utcnow
from app.core.db import SessionDep
from app.policy.usage import TrendGranularity, UsageAxis, UsageMetric
from app.repositories.usage_repository import UsageFilter
from app.schemas.usage import (
    AuthEventSummaryResponse,
    LeaderboardResponse,
    UsageOverviewResponse,
    UsageTrendResponse,
)
from app.services.usage_service import UsageService

router = APIRouter(tags=["Usage"], prefix="/usage")

#: 기본 조회 기간. 지정하지 않으면 최근 30일(UTC 일자 기준)입니다.
DEFAULT_RANGE_DAYS = 30


def _default_range() -> tuple[date, date]:
    today = utcnow().date()
    return today - timedelta(days=DEFAULT_RANGE_DAYS), today


def _range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    default_from, default_to = _default_range()
    return from_date or default_from, to_date or default_to


FromQuery = Query(default=None, description="시작 일자(UTC, 포함). 기본값은 30일 전")
ToQuery = Query(default=None, description="종료 일자(UTC, 포함). 기본값은 오늘")


@router.get("/overview", response_model=UsageOverviewResponse)
async def get_usage_overview(
    actor: AdminDep,
    session: SessionDep,
    from_date: date | None = FromQuery,
    to_date: date | None = ToQuery,
    team_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = Query(default=None, max_length=128),
) -> UsageOverviewResponse:
    """대시보드 카드용 합계와 상위 팀/사용자/모델.

    네 조회를 한 응답으로 묶습니다. 카드마다 따로 호출하면 그 사이에 집계 job 이 돌아
    합계와 상위 목록의 기준 시점이 어긋납니다.
    """
    start, end = _range(from_date, to_date)
    return await UsageService().overview(
        session,
        actor=actor,
        from_date=start,
        to_date=end,
        requested=UsageFilter(team_id=team_id, user_id=user_id, model_alias=model_alias),
    )


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_usage_leaderboard(
    actor: AdminDep,
    session: SessionDep,
    axis: UsageAxis = Query(default=UsageAxis.TEAM),
    metric: UsageMetric = Query(default=UsageMetric.COST),
    from_date: date | None = FromQuery,
    to_date: date | None = ToQuery,
    team_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    virtual_key_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> LeaderboardResponse:
    """축 × 지표 리더보드. drill-down 은 필터를 걸어 같은 엔드포인트로 합니다.

    사용자 축에는 `(팀 공용 키)` 항목이 나올 수 있습니다 — `TEAM` 소유 VK 호출은 사람에
    귀속되지 않습니다. 빼고 보여주면 합계가 맞지 않습니다.
    """
    start, end = _range(from_date, to_date)
    return await UsageService().leaderboard(
        session,
        actor=actor,
        axis=axis,
        metric=metric,
        from_date=start,
        to_date=end,
        requested=UsageFilter(
            team_id=team_id,
            user_id=user_id,
            virtual_key_id=virtual_key_id,
            model_alias=model_alias,
        ),
        limit=limit,
    )


@router.get("/trend", response_model=UsageTrendResponse)
async def get_usage_trend(
    actor: AdminDep,
    session: SessionDep,
    granularity: TrendGranularity = Query(default=TrendGranularity.DAY),
    from_date: date | None = FromQuery,
    to_date: date | None = ToQuery,
    team_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    virtual_key_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = Query(default=None, max_length=128),
) -> UsageTrendResponse:
    """기간별 추이. 값이 없는 버킷은 **행이 없습니다** — 0 을 채우지 않습니다.

    비어 있는 것과 0 인 것은 다릅니다(집계가 아직 안 돈 날 vs 호출이 없던 날). 채우려면
    화면이 기간을 알고 채우는 편이 낫습니다.
    """
    start, end = _range(from_date, to_date)
    return await UsageService().trend(
        session,
        actor=actor,
        granularity=granularity,
        from_date=start,
        to_date=end,
        requested=UsageFilter(
            team_id=team_id,
            user_id=user_id,
            virtual_key_id=virtual_key_id,
            model_alias=model_alias,
        ),
    )


@router.get("/auth-events", response_model=AuthEventSummaryResponse)
async def get_auth_event_summary(
    actor: AdminDep,
    session: SessionDep,
    from_date: date | None = FromQuery,
    to_date: date | None = ToQuery,
    team_id: uuid.UUID | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    virtual_key_id: uuid.UUID | None = Query(default=None),
) -> AuthEventSummaryResponse:
    """정책 거절(401/403/429) 요약.

    `occurrence_count` 가 실제 실패 수입니다. gateway 가 연속 실패를 60초 창으로 묶어 한 행에
    기록하므로 **행 수로 세면 과소 계상됩니다**(09 문서).
    """
    start, end = _range(from_date, to_date)
    return await UsageService().auth_events(
        session,
        actor=actor,
        from_date=start,
        to_date=end,
        requested=UsageFilter(team_id=team_id, user_id=user_id, virtual_key_id=virtual_key_id),
    )
