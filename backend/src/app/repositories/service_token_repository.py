"""서비스 토큰 쿼리. 세션은 service 가 만들어 넘깁니다."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import ServiceToken


class ServiceTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, token_id: uuid.UUID) -> ServiceToken | None:
        return await self._session.get(ServiceToken, token_id)

    async def list_all(self, *, include_revoked: bool = False) -> list[ServiceToken]:
        stmt = select(ServiceToken).order_by(ServiceToken.created_at.desc())
        if not include_revoked:
            stmt = stmt.where(ServiceToken.revoked_at.is_(None))
        return list((await self._session.execute(stmt)).scalars().all())

    def add(self, token: ServiceToken) -> None:
        self._session.add(token)
