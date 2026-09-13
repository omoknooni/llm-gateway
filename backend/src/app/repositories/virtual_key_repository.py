from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models.auth import VirtualKey, VirtualKeyAllowedModel
from app.models.enums import VKOwnerType, VKStatus
from app.policy.virtual_key import LIVE_STATUSES as _LIVE

#: 인증을 통과할 수 있는 상태. 규칙의 원천은 app.policy.virtual_key 입니다(08 문서 C1).
LIVE_STATUSES = tuple(_LIVE)


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

    async def list_keys(
        self,
        *,
        owner_type: VKOwnerType | None = None,
        owner_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        status: VKStatus | None = None,
        expires_before: datetime | None = None,
        unused_since: datetime | None = None,
        query: str | None = None,
        limit: int = 50,
        cursor_key: tuple | None = None,
    ) -> list[VirtualKey]:
        stmt = select(VirtualKey).order_by(VirtualKey.created_at.desc(), VirtualKey.id.desc()).limit(limit)
        if owner_type is not None:
            stmt = stmt.where(VirtualKey.owner_type == owner_type)
        if owner_id is not None:
            stmt = stmt.where(VirtualKey.owner_id == owner_id)
        if team_id is not None:
            stmt = stmt.where(VirtualKey.team_id == team_id)
        if status is not None:
            stmt = stmt.where(VirtualKey.status == status)
        if expires_before is not None:
            stmt = stmt.where(VirtualKey.expires_at.is_not(None), VirtualKey.expires_at < expires_before)
        if unused_since is not None:
            # 한 번도 쓰이지 않은 키도 '장기 미사용'입니다.
            stmt = stmt.where(
                (VirtualKey.last_used_at.is_(None)) | (VirtualKey.last_used_at < unused_since)
            )
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(VirtualKey.name.ilike(pattern) | VirtualKey.key_prefix.ilike(pattern))
        if cursor_key is not None:
            created_at, key_id = cursor_key
            stmt = stmt.where(
                (VirtualKey.created_at < created_at)
                | ((VirtualKey.created_at == created_at) & (VirtualKey.id < key_id))
            )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_live_for_team(self, team_id: uuid.UUID) -> list[VirtualKey]:
        stmt = select(VirtualKey).where(
            VirtualKey.team_id == team_id, VirtualKey.status.in_(LIVE_STATUSES)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_expired_candidates(self, *, now: datetime, limit: int) -> list[VirtualKey]:
        """만료 시각이 지났는데 아직 상태가 남아 있는 키."""
        stmt = (
            select(VirtualKey)
            .where(
                VirtualKey.status.in_(LIVE_STATUSES),
                VirtualKey.expires_at.is_not(None),
                VirtualKey.expires_at <= now,
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def names_for(self, key_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """id → 키 이름. 리더보드에 UUID 대신 이름을 붙일 때 씁니다."""
        if not key_ids:
            return {}
        stmt = select(VirtualKey.id, VirtualKey.name).where(VirtualKey.id.in_(key_ids))
        return {row.id: row.name for row in (await self._session.execute(stmt))}

    async def count_keys(self, *, team_id: uuid.UUID | None = None, status: VKStatus | None = None) -> int:
        stmt = select(func.count()).select_from(VirtualKey)
        if team_id is not None:
            stmt = stmt.where(VirtualKey.team_id == team_id)
        if status is not None:
            stmt = stmt.where(VirtualKey.status == status)
        return int((await self._session.execute(stmt)).scalar_one())

    async def revoke_team_keys(
        self, team_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str
    ) -> list[str]:
        """팀의 살아 있는 키를 전부 폐기하고 무효화할 key_hash 를 반환합니다."""
        hashes = await self.list_live_hashes_for_team(team_id)
        if not hashes:
            return []
        await self._session.execute(
            update(VirtualKey)
            .where(VirtualKey.team_id == team_id, VirtualKey.status.in_(LIVE_STATUSES))
            .values(
                status=VKStatus.REVOKED,
                revoked_at=utcnow(),
                revoked_by=actor_id,
                revoke_reason=reason,
            )
        )
        return hashes

    async def rotation_chain_ids(self, key_id: uuid.UUID) -> list[uuid.UUID]:
        """조상 방향 체인. 감사 화면이 '이 키의 조상은 무엇인가'를 보여줍니다."""
        chain: list[uuid.UUID] = [key_id]
        current = await self.get(key_id)
        seen = {key_id}
        while current is not None and current.rotated_from_id is not None:
            if current.rotated_from_id in seen:  # 방어적. 순환은 생기지 않아야 합니다.
                break
            seen.add(current.rotated_from_id)
            chain.append(current.rotated_from_id)
            current = await self.get(current.rotated_from_id)
        return chain

    async def list_allowed_models(self, key_id: uuid.UUID) -> list[str]:
        stmt = select(VirtualKeyAllowedModel.model_alias).where(
            VirtualKeyAllowedModel.virtual_key_id == key_id
        )
        return sorted((await self._session.execute(stmt)).scalars().all())

    async def replace_allowed_models(self, key_id: uuid.UUID, aliases: list[str]) -> None:
        await self._session.execute(
            delete(VirtualKeyAllowedModel).where(VirtualKeyAllowedModel.virtual_key_id == key_id)
        )
        self._session.add_all(
            [
                VirtualKeyAllowedModel(virtual_key_id=key_id, model_alias=alias)
                for alias in aliases
            ]
        )

    def add(self, key: VirtualKey) -> None:
        self._session.add(key)
