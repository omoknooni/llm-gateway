"""rate limit 설정과 해석.

집행과 카운팅은 gateway 가 합니다. 이 라우터는 **한도를 정의하고 해석 결과를 보여줄 뿐**입니다.

경로에 scope 를 박는 이유는, 같은 `PUT` 이라도 `GLOBAL`·`TEAM`·`USER`·`VIRTUAL_KEY` 의
권한과 계층 제약이 다르기 때문입니다. 하나의 `/rate-limits` 에 scope 를 본문으로 받으면
그 차이가 경로에서 보이지 않습니다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.auth import AdminDep, RequireAdmin, RequireAdminOrLeader
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.models.enums import RateLimitScope
from app.schemas.rate_limits import (
    EffectiveLimitsResponse,
    RateLimitListResponse,
    RateLimitSetRequest,
    RateLimitSetResponse,
    RateLimitTreeResponse,
    RateLimitUsageResponse,
)
from app.services.rate_limit_service import RateLimitService

router = APIRouter(tags=["Rate Limit"], prefix="/rate-limits")

#: 모델 차원. 지정하지 않으면 그 scope 의 **모든 모델**에 적용됩니다.
ModelQuery = Query(default=None, max_length=128, description="모델 alias. 생략하면 전체 모델")


@router.put("/global/{model_alias}", response_model=RateLimitSetResponse)
async def set_global_limit(
    model_alias: str,
    payload: RateLimitSetRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> RateLimitSetResponse:
    """전역 모델 한도.

    주체 한도와 **별개 축**입니다. 팀 한도가 아무리 낮아도 모든 팀의 합이 Bedrock 쿼터를
    넘을 수 있어, GLOBAL 은 항상 함께 검사됩니다.
    """
    return await RateLimitService(cache).set_limit(
        session,
        scope=RateLimitScope.GLOBAL,
        scope_id=None,
        model_alias=model_alias,
        data=payload,
        actor=actor,
        ctx=ctx,
    )


@router.put("/team/{team_id}", response_model=RateLimitSetResponse)
async def set_team_limit(
    team_id: uuid.UUID,
    payload: RateLimitSetRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    model_alias: str | None = ModelQuery,
) -> RateLimitSetResponse:
    """팀 한도. 이미 더 큰 멤버 한도가 있으면 **거절하지 않고** `conflicting_children` 으로 알립니다."""
    return await RateLimitService(cache).set_limit(
        session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=model_alias,
        data=payload,
        actor=actor,
        ctx=ctx,
    )


@router.put("/user/{user_id}", response_model=RateLimitSetResponse)
async def set_user_limit(
    user_id: uuid.UUID,
    payload: RateLimitSetRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    model_alias: str | None = ModelQuery,
) -> RateLimitSetResponse:
    """사용자 한도. 팀장이 설정하면 팀 한도를 넘을 수 없습니다(409 `limit_exceeds_parent`).

    ADMIN 은 이 제약을 받지 않지만 감사에 남고 응답에 `exceeds_parent` 가 붙습니다.
    """
    return await RateLimitService(cache).set_limit(
        session,
        scope=RateLimitScope.USER,
        scope_id=user_id,
        model_alias=model_alias,
        data=payload,
        actor=actor,
        ctx=ctx,
    )


@router.put("/virtual-key/{key_id}", response_model=RateLimitSetResponse)
async def set_virtual_key_limit(
    key_id: uuid.UUID,
    payload: RateLimitSetRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    model_alias: str | None = ModelQuery,
) -> RateLimitSetResponse:
    """VK 한도. 팀 공용 키 하나가 팀 전체 한도를 잡아먹는 것을 막는 자리입니다."""
    return await RateLimitService(cache).set_limit(
        session,
        scope=RateLimitScope.VIRTUAL_KEY,
        scope_id=key_id,
        model_alias=model_alias,
        data=payload,
        actor=actor,
        ctx=ctx,
    )


@router.get("", response_model=RateLimitListResponse)
async def list_rate_limits(
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    scope: RateLimitScope | None = Query(default=None),
    scope_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = ModelQuery,
) -> RateLimitListResponse:
    """설정 목록. 팀장은 자기 팀 축과 GLOBAL 만 봅니다.

    GLOBAL 을 함께 보여주는 이유는, 자기 한도가 왜 그런지 설명하려면 전역 축이 보여야 하기
    때문입니다.
    """
    return await RateLimitService(cache).list_limits(
        session, scope=scope, scope_id=scope_id, model_alias=model_alias, actor=actor
    )


@router.get("/effective", response_model=EffectiveLimitsResponse)
async def get_effective_limits(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    user_id: uuid.UUID | None = Query(default=None),
    virtual_key_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = ModelQuery,
) -> EffectiveLimitsResponse:
    """해석 결과와 근거. 대상을 지정하지 않으면 **자기 자신**입니다.

    주체 축과 전역 축을 따로 돌려줍니다 — 둘 다 통과해야 요청이 진행되므로, 합쳐 보여주면
    어느 쪽에서 막혔는지 알 수 없습니다.
    """
    return await RateLimitService(cache).effective(
        session,
        user_id=user_id,
        virtual_key_id=virtual_key_id,
        model_alias=model_alias,
        actor=actor,
    )


@router.get("/tree", response_model=RateLimitTreeResponse)
async def get_rate_limit_tree(
    team_id: uuid.UUID,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    model_alias: str | None = ModelQuery,
) -> RateLimitTreeResponse:
    """팀 → 멤버 트리. 상속과 상위 초과를 화면이 그대로 그릴 수 있게 만듭니다."""
    return await RateLimitService(cache).tree(
        session, team_id=team_id, model_alias=model_alias, actor=actor
    )


@router.get("/usage", response_model=RateLimitUsageResponse)
async def get_rate_limit_usage(
    actor: RequireAdminOrLeader,
    session: SessionDep,
    cache: CacheDep,
    scope: RateLimitScope | None = Query(default=None),
    scope_id: uuid.UUID | None = Query(default=None),
    model_alias: str | None = ModelQuery,
) -> RateLimitUsageResponse:
    """실시간 사용률. **best-effort** 입니다.

    현재는 항상 `available: false` 입니다 — gateway 집행 카운터 키의 최종 형태가 Phase 4
    미확정이라 키를 만들 수 없습니다. 응답 형태가 불가용을 정상 상태로 다루므로 화면은
    지금 붙여도 되고, 규약이 확정되면 값이 채워집니다(06 문서).
    """
    return await RateLimitService(cache).usage(
        session, scope=scope, scope_id=scope_id, model_alias=model_alias, actor=actor
    )


@router.delete("/{scope}/{scope_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_limit(
    scope: RateLimitScope,
    scope_id: str,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    model_alias: str | None = ModelQuery,
) -> None:
    """정의 전체 제거. `null` 저장과 다릅니다 — 이 층이 아예 없어지고 상위로 폴백합니다.

    `GLOBAL` 은 대상이 없으므로 `scope_id` 자리에 `global` 을 씁니다. 경로 형태를 scope 마다
    다르게 두지 않기 위한 자리표시자입니다.
    """
    resolved_id = None if scope == RateLimitScope.GLOBAL else uuid.UUID(scope_id)
    await RateLimitService(cache).delete_limit(
        session,
        scope=scope,
        scope_id=resolved_id,
        model_alias=model_alias,
        actor=actor,
        ctx=ctx,
    )
