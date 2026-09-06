"""팀/사용자 허용 모델 정책.

경로는 대상 리소스 아래에 둡니다. 정책이 팀과 사용자에 붙는다는 것이 경로에서 보여야 합니다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.auth import AdminDep, RequireAdmin, ensure_self_or_privileged, ensure_team_scope
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.schemas.models import AllowedModelsRequest, AllowedModelsResponse, EffectiveModelsResponse
from app.services.allowed_model_service import AllowedModelService

router = APIRouter(tags=["Allowed Models"])


@router.get("/teams/{team_id}/allowed-models", response_model=AllowedModelsResponse)
async def get_team_allowed_models(
    team_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep
) -> AllowedModelsResponse:
    ensure_team_scope(actor, team_id)
    return await AllowedModelService(cache).get_team_allowed(session, team_id)


@router.put("/teams/{team_id}/allowed-models", response_model=AllowedModelsResponse)
async def set_team_allowed_models(
    team_id: uuid.UUID,
    payload: AllowedModelsRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> AllowedModelsResponse:
    """전체 교체. **빈 배열은 팀 층에서 '제한 없음'** 을 뜻합니다."""
    return await AllowedModelService(cache).set_team_allowed(
        session, team_id=team_id, aliases=payload.model_aliases, actor=actor, ctx=ctx
    )


@router.get("/users/{user_id}/allowed-models", response_model=AllowedModelsResponse)
async def get_user_allowed_models(
    user_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep
) -> AllowedModelsResponse:
    ensure_self_or_privileged(actor, user_id)
    return await AllowedModelService(cache).get_user_allowed(session, user_id)


@router.put("/users/{user_id}/allowed-models", response_model=AllowedModelsResponse)
async def set_user_allowed_models(
    user_id: uuid.UUID,
    payload: AllowedModelsRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> AllowedModelsResponse:
    """전체 교체. **빈 배열은 사용자 층에서 'override 해제'** 이지 전체 허용이 아닙니다."""
    return await AllowedModelService(cache).set_user_allowed(
        session, user_id=user_id, aliases=payload.model_aliases, actor=actor, ctx=ctx
    )


@router.delete("/users/{user_id}/allowed-models", response_model=AllowedModelsResponse)
async def clear_user_allowed_models(
    user_id: uuid.UUID, actor: RequireAdmin, session: SessionDep, ctx: CtxDep, cache: CacheDep
) -> AllowedModelsResponse:
    """override 를 해제하고 팀 정책으로 복귀시킵니다."""
    return await AllowedModelService(cache).set_user_allowed(
        session, user_id=user_id, aliases=[], actor=actor, ctx=ctx
    )


@router.get("/users/{user_id}/effective-models", response_model=EffectiveModelsResponse)
async def get_effective_models(
    user_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep
) -> EffectiveModelsResponse:
    """해석 결과와 근거. '행 0개'의 의미가 층마다 달라 근거 표시가 필요합니다."""
    ensure_self_or_privileged(actor, user_id)
    return await AllowedModelService(cache).resolve_for_user(session, user_id)
