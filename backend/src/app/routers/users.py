"""사용자 관리와 조직 트리."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.auth import AdminDep, RequireAdmin, ensure_team_scope
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.core.exceptions import ForbiddenError
from app.models.enums import UserRole
from app.schemas.auth import MeResponse
from app.schemas.common import Page
from app.schemas.users import (
    OrgTreeTeam,
    UserCreateRequest,
    UserDeactivateResponse,
    UserResponse,
    UserTeamTransferRequest,
    UserTransferResponse,
    UserUpdateRequest,
)
from app.services.user_service import UserService

router = APIRouter(tags=["User"])


@router.get("/me", response_model=MeResponse)
async def get_me(actor: AdminDep) -> MeResponse:
    return MeResponse(
        user_id=str(actor.user_id),
        email=actor.email,
        role=actor.role.value,
        team_id=str(actor.team_id) if actor.team_id else None,
        is_service_token=actor.is_service_token,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest, actor: RequireAdmin, session: SessionDep, ctx: CtxDep, cache: CacheDep
) -> UserResponse:
    return await UserService(cache).create(session, data=payload, actor=actor, ctx=ctx)


@router.get("/users", response_model=Page[UserResponse])
async def list_users(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    team_id: uuid.UUID | None = Query(default=None),
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="이메일 또는 표시명 부분 일치"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[UserResponse]:
    if not actor.is_admin:
        # TEAM_LEADER 는 자기 팀만. 다른 팀을 지정하면 403 입니다.
        if team_id is not None:
            ensure_team_scope(actor, team_id)
        team_id = actor.team_id
        if team_id is None:
            raise ForbiddenError("팀에 소속되지 않은 사용자는 목록을 조회할 수 없습니다")

    return await UserService(cache).list_users(
        session,
        team_id=team_id,
        role=role,
        is_active=is_active,
        query=q,
        cursor=cursor,
        limit=limit,
    )


@router.get("/users/tree", response_model=list[OrgTreeTeam])
async def get_org_tree(actor: AdminDep, session: SessionDep, cache: CacheDep) -> list[OrgTreeTeam]:
    tree = await UserService(cache).org_tree(session)
    if actor.is_admin:
        return tree
    return [team for team in tree if actor.team_id and team.id == str(actor.team_id)]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep
) -> UserResponse:
    user = await UserService(cache).get(session, user_id)
    if actor.is_admin or actor.user_id == user_id:
        return user
    ensure_team_scope(actor, uuid.UUID(user.team_id) if user.team_id else None)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> UserResponse:
    return await UserService(cache).update(
        session, user_id=user_id, data=payload, actor=actor, ctx=ctx
    )


@router.post("/users/{user_id}/deactivate", response_model=UserDeactivateResponse)
async def deactivate_user(
    user_id: uuid.UUID, actor: RequireAdmin, session: SessionDep, ctx: CtxDep, cache: CacheDep
) -> UserDeactivateResponse:
    """논리적 오프보딩. 소유 VK 를 전부 폐기하고 인증 캐시를 지웁니다."""
    return await UserService(cache).deactivate(session, user_id=user_id, actor=actor, ctx=ctx)


@router.put("/users/{user_id}/team", response_model=UserTransferResponse)
async def transfer_user_team(
    user_id: uuid.UUID,
    payload: UserTeamTransferRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> UserTransferResponse:
    """팀 이동. VK 는 폐기하지 않고 인증 캐시만 무효화합니다(02 문서)."""
    team_id = uuid.UUID(payload.team_id) if payload.team_id else None
    return await UserService(cache).transfer_team(
        session, user_id=user_id, team_id=team_id, reason=payload.reason, actor=actor, ctx=ctx
    )
