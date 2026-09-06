from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.auth import VirtualKey
from app.models.enums import VKStatus

#: 인증을 통과할 수 있는 상태. gateway 와 공유하는 계약입니다(08 문서 C1).
LIVE_STATUSES = (VKStatus.ACTIVE, VKStatus.ROTATED)


class VirtualKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key_id: uuid.UUID, *, for_update: bool = False) -> VirtualKey | None:
        stmt = select(VirtualKey).where(VirtualKey.id == key_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_live_hashes_for_user(self, user_id: uuid.UUID) -> list[str]:
        """캐시 무효화 대상 계산용. 팬아웃은 DB 에서 정확히 구합니다(08 문서 C2)."""
        stmt = select(VirtualKey.key_hash).where(
            VirtualKey.owner_id == user_id, VirtualKey.status.in_(LIVE_STATUSES)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_live_hashes_for_team(self, team_id: uuid.UUID) -> list[str]:
        stmt = select(VirtualKey.key_hash).where(
            VirtualKey.team_id == team_id, VirtualKey.status.in_(LIVE_STATUSES)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def revoke_all_for_owner(
        self, owner_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str
    ) -> list[str]:
        """소유자의 살아 있는 키를 전부 폐기하고, 무효화할 key_hash 목록을 반환합니다."""
        hashes = await self.list_live_hashes_for_user(owner_id)
        if not hashes:
            return []
        await self._session.execute(
            update(VirtualKey)
            .where(VirtualKey.owner_id == owner_id, VirtualKey.status.in_(LIVE_STATUSES))
            .values(
                status=VKStatus.REVOKED,
                revoked_at=utcnow(),
                revoked_by=actor_id,
                revoke_reason=reason,
            )
        )
        return hashes

    async def move_owner_keys_to_team(self, owner_id: uuid.UUID, team_id: uuid.UUID) -> list[str]:
        """사용자 팀 이동 시 소유 키의 비정규화된 team_id 를 따라 옮깁니다."""
        hashes = await self.list_live_hashes_for_user(owner_id)
        await self._session.execute(
            update(VirtualKey).where(VirtualKey.owner_id == owner_id).values(team_id=team_id)
        )
        return hashes
