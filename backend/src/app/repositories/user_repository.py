from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.enums import UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID, *, for_update: bool = False) -> User | None:
        stmt = select(User).where(User.id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        return (
            await self._session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

    async def list_users(
        self,
        *,
        team_id: uuid.UUID | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        query: str | None = None,
        limit: int = 50,
        cursor_key: tuple | None = None,
    ) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc()).limit(limit)
        if team_id is not None:
            stmt = stmt.where(User.team_id == team_id)
        if role is not None:
            stmt = stmt.where(User.role == role)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(User.email.ilike(pattern) | User.display_name.ilike(pattern))
        if cursor_key is not None:
            created_at, user_id = cursor_key
            stmt = stmt.where(
                (User.created_at < created_at)
                | ((User.created_at == created_at) & (User.id < user_id))
            )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_by_team(self, team_id: uuid.UUID) -> list[User]:
        stmt = select(User).where(User.team_id == team_id).order_by(User.display_name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_active_admins(self, *, excluding: uuid.UUID | None = None) -> int:
        stmt = select(func.count()).select_from(User).where(
            User.role == UserRole.ADMIN, User.is_active.is_(True)
        )
        if excluding is not None:
            stmt = stmt.where(User.id != excluding)
        return int((await self._session.execute(stmt)).scalar_one())

    def add(self, user: User) -> None:
        self._session.add(user)
