"""팀 관리."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.auth import AdminDep, RequireAdmin, ensure_team_scope
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.schemas.common import Page
from app.schemas.teams import TeamCreateRequest, TeamLeaderRequest, TeamResponse, TeamUpdateRequest
from app.schemas.users import UserResponse
from app.services.team_service import TeamService
from app.services.user_service import to_response

router = APIRouter(prefix="/teams", tags=["Team"])


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreateRequest, actor: RequireAdmin, session: SessionDep, ctx: CtxDep, cache: CacheDep
) -> TeamResponse:
    return await TeamService(cache).create(session, data=payload, actor=actor, ctx=ctx)


@router.get("", response_model=Page[TeamResponse])
async def list_teams(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    is_active: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[TeamResponse]:
    page = await TeamService(cache).list_teams(
        session, is_active=is_active, cursor=cursor, limit=limit
    )
    if actor.is_admin:
        return page
    # ADMIN 이 아니면 자기 팀만 보입니다.
    items = [team for team in page.items if actor.team_id and team.id == str(actor.team_id)]
    return Page[TeamResponse](items=items, next_cursor=page.next_cursor, has_more=page.has_more)


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep) -> TeamResponse:
    ensure_team_scope(actor, team_id)
    return await TeamService(cache).get(session, team_id)


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    payload: TeamUpdateRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> TeamResponse:
    return await TeamService(cache).update(
        session, team_id=team_id, data=payload, actor=actor, ctx=ctx
    )


@router.put("/{team_id}/leader", response_model=TeamResponse)
async def set_team_leader(
    team_id: uuid.UUID,
    payload: TeamLeaderRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> TeamResponse:
    """팀장 지정/해제. `user_id` 가 null 이면 해제입니다."""
    user_id = uuid.UUID(payload.user_id) if payload.user_id else None
    return await TeamService(cache).set_leader(
        session, team_id=team_id, user_id=user_id, actor=actor, ctx=ctx
    )


@router.get("/{team_id}/members", response_model=list[UserResponse])
async def list_team_members(
    team_id: uuid.UUID, actor: AdminDep, session: SessionDep
) -> list[UserResponse]:
    ensure_team_scope(actor, team_id)
    from app.repositories.user_repository import UserRepository

    members = await UserRepository(session).list_by_team(team_id)
    return [to_response(member) for member in members]

