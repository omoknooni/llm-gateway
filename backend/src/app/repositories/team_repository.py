from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Team, User


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, team_id: uuid.UUID, *, for_update: bool = False) -> Team | None:
        stmt = select(Team).where(Team.id == team_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, name: str) -> Team | None:
        return (
            await self._session.execute(select(Team).where(Team.name == name))
        ).scalar_one_or_none()

    async def list_teams(
        self, *, is_active: bool | None = None, limit: int = 50, cursor_key: tuple | None = None
    ) -> list[Team]:
        stmt = select(Team).order_by(Team.created_at.desc(), Team.id.desc()).limit(limit)
        if is_active is not None:
            stmt = stmt.where(Team.is_active.is_(is_active))
        if cursor_key is not None:
            created_at, team_id = cursor_key
            stmt = stmt.where(
                (Team.created_at < created_at)
                | ((Team.created_at == created_at) & (Team.id < team_id))
            )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all_active(self) -> list[Team]:
        stmt = select(Team).where(Team.is_active.is_(True)).order_by(Team.name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_active_members(self, team_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(User).where(
            User.team_id == team_id, User.is_active.is_(True)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    def add(self, team: Team) -> None:
        self._session.add(team)
