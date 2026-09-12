"""예산 설정·배분·소진 조회.

집행은 gateway 가 합니다. 이 라우터는 정책을 쓰고 소진을 보여줄 뿐입니다(05 문서).

경로는 `/budgets/{scope}/{id}` 형태로 scope 를 앞에 둡니다. 팀 예산과 사용자 예산은 한도의
상하 관계가 있어(배분 합계 ≤ 팀 한도) 같은 리소스 계열로 읽히는 편이 낫습니다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.auth import AdminDep, RequireAdmin, RequireAdminOrLeader, ensure_team_scope
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep, RedisDep
from app.models.enums import BudgetScope
from app.policy.budget import PERIOD_PATTERN
from app.schemas.budgets import (
    AllocationResponse,
    AllocationSetRequest,
    BudgetConfigResponse,
    BudgetSetRequest,
    BudgetSummaryResponse,
    MyBudgetResponse,
    ReseedRequest,
    ReseedResponse,
    TeamBudgetUsageResponse,
    UnsetBudgetResponse,
    UserBudgetUsageResponse,
)
from app.services.budget_service import BudgetService

router = APIRouter(tags=["Budget"])

#: `YYYY-MM`. 미지정이면 현재 월(UTC)입니다 — 표시는 KST 라도 경계는 UTC 입니다(05 문서).
PeriodQuery = Query(default=None, pattern=PERIOD_PATTERN, description="UTC 기준 월. 'YYYY-MM'")


@router.put("/budgets/team/{team_id}", response_model=BudgetConfigResponse)
async def set_team_budget(
    team_id: uuid.UUID,
    payload: BudgetSetRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> BudgetConfigResponse:
    """팀 예산 설정(upsert).

    이전 설정은 닫히고 새 행이 생깁니다. 한도 변경은 즉시 유효하며 당월 소진에는 영향이 없습니다.
    """
    return await BudgetService(cache, redis).set_team_budget(
        session, team_id=team_id, data=payload, actor=actor, ctx=ctx
    )


@router.delete("/budgets/team/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_team_budget(
    team_id: uuid.UUID,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> None:
    """예산 해제. **무제한**이 됩니다 — 미설정은 차단하지 않습니다(05 문서)."""
    await BudgetService(cache, redis).clear_team_budget(
        session, team_id=team_id, actor=actor, ctx=ctx
    )


@router.put("/budgets/user/{user_id}", response_model=BudgetConfigResponse)
async def set_user_budget(
    user_id: uuid.UUID,
    payload: BudgetSetRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> BudgetConfigResponse:
    """사용자 예산 설정. 팀장은 자기 팀 멤버만, 그리고 팀 한도 안에서만 가능합니다."""
    return await BudgetService(cache, redis).set_user_budget(
        session, user_id=user_id, data=payload, actor=actor, ctx=ctx
    )


@router.delete("/budgets/user/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_user_budget(
    user_id: uuid.UUID,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> None:
    await BudgetService(cache, redis).clear_user_budget(
        session, user_id=user_id, actor=actor, ctx=ctx
    )


@router.get("/budgets/team/{team_id}/allocation", response_model=AllocationResponse)
async def get_team_allocation(
    team_id: uuid.UUID,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    period: str | None = PeriodQuery,
) -> AllocationResponse:
    """배분 현황. 팀 한도, 배분 합계, 미배분 여유분을 함께 돌려줍니다."""
    ensure_team_scope(actor, team_id)
    return await BudgetService(cache, redis).get_allocation(session, team_id=team_id, period=period)


@router.put("/budgets/team/{team_id}/allocation", response_model=AllocationResponse)
async def set_team_allocation(
    team_id: uuid.UUID,
    payload: AllocationSetRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> AllocationResponse:
    """배분 일괄 설정.

    **전체 교체**이고 원자적입니다. 합계가 팀 한도를 넘으면 409 `allocation_exceeds_team_budget`
    으로 전체를 거절합니다. 팀장은 배분만 할 수 있고 팀 한도 자체는 바꿀 수 없습니다.
    """
    return await BudgetService(cache, redis).set_allocation(
        session, team_id=team_id, data=payload, actor=actor, ctx=ctx
    )


@router.get("/budgets/summary", response_model=BudgetSummaryResponse)
async def get_budget_summary(
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    scope: BudgetScope = Query(default=BudgetScope.TEAM),
    period: str | None = PeriodQuery,
) -> BudgetSummaryResponse:
    """기간별 소진 요약. 소진율 내림차순입니다.

    ADMIN 은 전체, 팀장은 자기 팀(과 그 멤버)만 봅니다. MEMBER 는 `/me/budget` 을 씁니다 —
    `ensure_team_scope` 는 역할을 보지 않으므로 의존성에서 걸러야 합니다(00 문서 인가 표).
    """
    return await BudgetService(cache, redis).summary(
        session, scope=scope, period=period, actor=actor
    )


@router.get("/budgets/unset", response_model=UnsetBudgetResponse)
async def list_unset_budgets(
    actor: RequireAdmin,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    team_id: uuid.UUID | None = Query(default=None),
) -> UnsetBudgetResponse:
    """예산 미설정 목록. 미설정은 무제한이므로 상시 노출이 유일한 방어선입니다."""
    return await BudgetService(cache, redis).unset_budgets(session, team_id=team_id)


@router.put("/budgets/usages/reseed", response_model=ReseedResponse)
async def reseed_budget_usage(
    payload: ReseedRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    redis: RedisDep,
) -> ReseedResponse:
    """소진값 재시드. **운영 예외**입니다.

    control plane 이 집행 카운터를 쓰는 유일한 경로이며, 사유가 필수이고 감사에 before/after 가
    남습니다. 자동 경로가 아니라 사람이 부르는 복구 도구입니다(05 문서).
    """
    return await BudgetService(cache, redis).reseed(session, data=payload, actor=actor, ctx=ctx)


@router.get("/budgets/team/{team_id}/usage", response_model=TeamBudgetUsageResponse)
async def get_team_budget_usage(
    team_id: uuid.UUID,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    period: str | None = PeriodQuery,
) -> TeamBudgetUsageResponse:
    """팀 소진 상세 + 멤버·모델 breakdown.

    breakdown 은 월 집계 테이블에서 옵니다. 집계 job(M7)이 돌기 전에는 빈 목록입니다.
    """
    ensure_team_scope(actor, team_id)
    return await BudgetService(cache, redis).team_usage(session, team_id=team_id, period=period)


@router.get("/budgets/user/{user_id}/usage", response_model=UserBudgetUsageResponse)
async def get_user_budget_usage(
    user_id: uuid.UUID,
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    period: str | None = PeriodQuery,
) -> UserBudgetUsageResponse:
    """사용자 소진 상세. ADMIN / 팀장(자기 팀) / 본인."""
    return await BudgetService(cache, redis).user_usage(
        session, user_id=user_id, actor=actor, period=period
    )


@router.get("/me/budget", response_model=MyBudgetResponse)
async def get_my_budget(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    redis: RedisDep,
    period: str | None = PeriodQuery,
) -> MyBudgetResponse:
    """내 예산과 소진율. 사용자 예산과 팀 예산을 함께 돌려줍니다 — 둘 다 집행에 쓰입니다."""
    return await BudgetService(cache, redis).my_budget(session, actor=actor, period=period)
