"""팀 관리.

팀은 정책 부착점입니다. 예산·rate limit·허용 모델·VK 소유권·사용량 집계가 전부 이 축에 붙습니다.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.auth import CurrentAdmin
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.deps import RequestContext
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.models.auth import Team
from app.models.enums import UserRole
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page
from app.schemas.teams import TeamCreateRequest, TeamResponse, TeamUpdateRequest


def to_response(team: Team) -> TeamResponse:
    return TeamResponse(
        id=str(team.id),
        name=team.name,
        description=team.description,
        leader_user_id=str(team.leader_user_id) if team.leader_user_id else None,
        is_active=team.is_active,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


class TeamService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    async def create(
        self, session: AsyncSession, *, data: TeamCreateRequest, actor: CurrentAdmin, ctx: RequestContext
    ) -> TeamResponse:
        repo = TeamRepository(session)
        if await repo.get_by_name(data.name) is not None:
            raise ConflictError("같은 이름의 팀이 이미 있습니다", code="duplicate_team_name")

        team = Team(id=uuid.uuid4(), name=data.name, description=data.description)
        repo.add(team)
        await audit.record_for(
            session,
            actor,
            action="CREATE_TEAM",
            resource_type="team",
            resource_id=str(team.id),
            changes={"after": {"name": team.name}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(team)
        return to_response(team)

    async def get(self, session: AsyncSession, team_id: uuid.UUID) -> TeamResponse:
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))
        return to_response(team)

    async def list_teams(
        self,
        session: AsyncSession,
        *,
        is_active: bool | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[TeamResponse]:
        repo = TeamRepository(session)
        cursor_key = decode_cursor(cursor) if cursor else None
        rows = await repo.list_teams(is_active=is_active, limit=limit + 1, cursor_key=cursor_key)

        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return Page[TeamResponse](
            items=[to_response(team) for team in rows], next_cursor=next_cursor, has_more=has_more
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        data: TeamUpdateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> TeamResponse:
        repo = TeamRepository(session)
        team = await repo.get(team_id, for_update=True)
        if team is None:
            raise NotFoundError("Team", str(team_id))

        before = {"name": team.name, "description": team.description, "is_active": team.is_active}

        if data.name is not None and data.name != team.name:
            if await repo.get_by_name(data.name) is not None:
                raise ConflictError("같은 이름의 팀이 이미 있습니다", code="duplicate_team_name")
            team.name = data.name
        if data.description is not None:
            team.description = data.description
        if data.is_active is not None and data.is_active != team.is_active:
            if not data.is_active and await repo.count_active_members(team_id) > 0:
                # 활성 멤버가 남은 팀을 비활성화하면 그 사람들의 정책 부착점이 사라집니다.
                raise ConflictError(
                    "활성 멤버가 있는 팀은 비활성화할 수 없습니다", code="team_has_active_members"
                )
            team.is_active = data.is_active

        after = {"name": team.name, "description": team.description, "is_active": team.is_active}
        await audit.record_for(
            session,
            actor,
            action="UPDATE_TEAM" if team.is_active else "DEACTIVATE_TEAM",
            resource_type="team",
            resource_id=str(team.id),
            changes={"before": before, "after": after},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(team)
        return to_response(team)

    async def set_leader(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        user_id: uuid.UUID | None,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> TeamResponse:
        """팀장 지정/해제.

        역할(`UserRole.TEAM_LEADER`)과 팀장 지정(`teams.leader_user_id`)은 별개입니다.
        역할은 권한이고 팀장 지정은 소속 관계입니다. 지정 시 역할을 올리되, 해제 시
        자동으로 내리지는 않습니다(다른 팀의 팀장일 수 있습니다).
        """
        team = await TeamRepository(session).get(team_id, for_update=True)
        if team is None:
            raise NotFoundError("Team", str(team_id))

        before_leader = team.leader_user_id
        promoted = False

        if user_id is None:
            team.leader_user_id = None
        else:
            user = await UserRepository(session).get(user_id, for_update=True)
            if user is None:
                raise NotFoundError("User", str(user_id))
            if user.team_id != team_id:
                raise ValidationError(
                    "팀 소속이 아닌 사용자는 팀장이 될 수 없습니다", code="leader_not_in_team"
                )
            team.leader_user_id = user.id
            if user.role == UserRole.MEMBER:
                user.role = UserRole.TEAM_LEADER
                promoted = True

        await audit.record_for(
            session,
            actor,
            action="SET_TEAM_LEADER",
            resource_type="team",
            resource_id=str(team.id),
            changes={
                "before": {"leader_user_id": str(before_leader) if before_leader else None},
                "after": {
                    "leader_user_id": str(team.leader_user_id) if team.leader_user_id else None,
                    "role_promoted": promoted,
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(team)
        return to_response(team)
