"""Virtual Key 발급·로테이션·폐기.

키 **원문도 암호문도 저장하지 않습니다.** `sha256(원문)` 과 표시용 prefix 만 둡니다(03 문서).
원문은 발급/로테이션 응답에서 한 번만 반환되고, 이후 어떤 API 로도 다시 볼 수 없습니다.

폐기는 즉시 반영되어야 하므로 캐시 삭제가 선택이 아니라 필수입니다. 삭제 실패는 응답에 드러냅니다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin, hash_token
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.deps import RequestContext
from app.core.exceptions import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.models.audit import AuditLog
from app.models.auth import VirtualKey
from app.models.enums import VKOwnerType, VKStatus
from app.policy import virtual_key as vk_policy
from app.repositories.model_repository import AllowedModelRepository, ModelAliasRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.repositories.virtual_key_repository import VirtualKeyRepository
from app.schemas.common import Page
from app.schemas.virtual_keys import (
    TeamRevokeAllResponse,
    VirtualKeyAuditEntry,
    VirtualKeyAuditResponse,
    VirtualKeyCreateRequest,
    VirtualKeyCreateResponse,
    VirtualKeyResponse,
    VirtualKeyRotateRequest,
    VirtualKeyUpdateRequest,
)

logger = structlog.get_logger()


def _to_response(key: VirtualKey, allowed: list[str]) -> VirtualKeyResponse:
    return VirtualKeyResponse(
        id=str(key.id),
        name=key.name,
        key_prefix=key.key_prefix,
        owner_type=key.owner_type,
        owner_id=str(key.owner_id),
        team_id=str(key.team_id),
        status=key.status,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        rotated_from_id=str(key.rotated_from_id) if key.rotated_from_id else None,
        revoked_at=key.revoked_at,
        revoke_reason=key.revoke_reason,
        allowed_model_aliases=allowed,
        created_at=key.created_at,
        updated_at=key.updated_at,
    )


class VirtualKeyService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    # ── 발급 ──

    async def issue(
        self,
        session: AsyncSession,
        *,
        data: VirtualKeyCreateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> VirtualKeyCreateResponse:
        settings = get_settings()
        owner_id = uuid.UUID(data.owner_id)
        team_id = await self._resolve_owner_team(session, data.owner_type, owner_id)

        self._validate_expiry(data.expires_at, max_days=settings.VIRTUAL_KEY_MAX_TTL_DAYS)
        allowed = await self._validate_key_allowlist(
            session, owner_type=data.owner_type, owner_id=owner_id, team_id=team_id,
            aliases=data.allowed_model_aliases,
        )

        raw, prefix = vk_policy.generate_key(settings.VIRTUAL_KEY_ENV)
        key = VirtualKey(
            id=uuid.uuid4(),
            name=data.name,
            key_hash=hash_token(raw),
            key_prefix=prefix,
            owner_type=data.owner_type,
            owner_id=owner_id,
            team_id=team_id,
            status=VKStatus.ACTIVE,
            expires_at=data.expires_at,
            created_by=actor.user_id,
        )
        repo = VirtualKeyRepository(session)
        repo.add(key)
        await session.flush()
        await repo.replace_allowed_models(key.id, allowed)

        await audit.record_for(
            session,
            actor,
            action="CREATE_VIRTUAL_KEY",
            resource_type="virtual_key",
            resource_id=str(key.id),
            # key_hash 와 원문은 남기지 않습니다. prefix 만 남깁니다.
            changes={
                "after": {
                    "name": key.name,
                    "key_prefix": prefix,
                    "owner_type": key.owner_type.value,
                    "owner_id": str(owner_id),
                    "expires_at": data.expires_at.isoformat(),
                    "allowed_model_aliases": allowed,
                }
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        # 같은 해시가 있을 리 없지만 방어적으로 지웁니다.
        await self._cache.invalidate([cache_keys.vk_auth(key.key_hash)])

        await session.refresh(key)
        return VirtualKeyCreateResponse(**_to_response(key, allowed).model_dump(), virtual_key=raw)

    # ── 조회 ──

    async def get(self, session: AsyncSession, key_id: uuid.UUID) -> VirtualKeyResponse:
        repo = VirtualKeyRepository(session)
        key = await repo.get(key_id)
        if key is None:
            raise NotFoundError("VirtualKey", str(key_id))
        return _to_response(key, await repo.list_allowed_models(key_id))

    async def list_keys(
        self,
        session: AsyncSession,
        *,
        owner_type: VKOwnerType | None = None,
        owner_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        status: VKStatus | None = None,
        expires_before: datetime | None = None,
        unused_since: datetime | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[VirtualKeyResponse]:
        repo = VirtualKeyRepository(session)
        rows = await repo.list_keys(
            owner_type=owner_type,
            owner_id=owner_id,
            team_id=team_id,
            status=status,
            expires_before=expires_before,
            unused_since=unused_since,
            query=query,
            limit=limit + 1,
            cursor_key=decode_cursor(cursor) if cursor else None,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None

        items = [_to_response(key, await repo.list_allowed_models(key.id)) for key in rows]
        return Page[VirtualKeyResponse](items=items, next_cursor=next_cursor, has_more=has_more)

    async def get_audit(self, session: AsyncSession, key_id: uuid.UUID) -> VirtualKeyAuditResponse:
        """이 키와 로테이션 체인 전체의 감사 이력."""
        repo = VirtualKeyRepository(session)
        if await repo.get(key_id) is None:
            raise NotFoundError("VirtualKey", str(key_id))

        chain = await repo.rotation_chain_ids(key_id)
        rows = (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.resource_type == "virtual_key",
                    AuditLog.resource_id.in_([str(item) for item in chain]),
                )
                .order_by(AuditLog.occurred_at)
            )
        ).scalars().all()

        return VirtualKeyAuditResponse(
            key_id=str(key_id),
            rotation_chain=[str(item) for item in chain],
            entries=[
                VirtualKeyAuditEntry(
                    occurred_at=row.occurred_at,
                    actor_user_id=str(row.actor_user_id),
                    actor_role=row.actor_role,
                    action=row.action,
                    resource_id=row.resource_id,
                    changes=row.changes,
                    result=row.result,
                )
                for row in rows
            ],
        )

    # ── 수정 ──

    async def update(
        self,
        session: AsyncSession,
        *,
        key_id: uuid.UUID,
        data: VirtualKeyUpdateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> VirtualKeyResponse:
        repo = VirtualKeyRepository(session)
        key = await repo.get(key_id, for_update=True)
        if key is None:
            raise NotFoundError("VirtualKey", str(key_id))
        if key.status in vk_policy.TERMINAL_STATUSES:
            raise InvalidStateTransitionError(f"{key.status.value} 상태의 키는 수정할 수 없습니다")

        before_allowed = await repo.list_allowed_models(key_id)
        before = {"name": key.name, "expires_at": key.expires_at.isoformat() if key.expires_at else None}

        if data.name is not None:
            key.name = data.name
        if data.expires_at is not None:
            # 연장은 허용하지 않습니다. 수명을 늘리려면 새 키를 발급해야 감사에 남습니다.
            if key.expires_at is not None and data.expires_at > key.expires_at:
                raise ValidationError(
                    "만료 시각은 단축만 가능합니다", code="expiry_extension_not_allowed"
                )
            self._validate_expiry(data.expires_at, max_days=get_settings().VIRTUAL_KEY_MAX_TTL_DAYS)
            key.expires_at = data.expires_at

        allowed = before_allowed
        if data.allowed_model_aliases is not None:
            allowed = await self._validate_key_allowlist(
                session,
                owner_type=key.owner_type,
                owner_id=key.owner_id,
                team_id=key.team_id,
                aliases=data.allowed_model_aliases,
            )
            await repo.replace_allowed_models(key_id, allowed)

        await audit.record_for(
            session,
            actor,
            action="UPDATE_VIRTUAL_KEY",
            resource_type="virtual_key",
            resource_id=str(key_id),
            changes={
                "before": {**before, "allowed_model_aliases": before_allowed},
                "after": {
                    "name": key.name,
                    "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                    "allowed_model_aliases": allowed,
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await self._cache.invalidate([cache_keys.vk_auth(key.key_hash)])

        await session.refresh(key)
        return _to_response(key, allowed)

    # ── 로테이션 ──

    async def rotate(
        self,
        session: AsyncSession,
        *,
        key_id: uuid.UUID,
        data: VirtualKeyRotateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> VirtualKeyCreateResponse:
        """유예 기간을 둔 교체. '폐기 후 재발급'이 아닙니다. 무중단 전환이 목적입니다."""
        settings = get_settings()
        repo = VirtualKeyRepository(session)
        old = await repo.get(key_id, for_update=True)
        if old is None:
            raise NotFoundError("VirtualKey", str(key_id))
        if not vk_policy.is_transition_allowed(old.status, VKStatus.ROTATED):
            raise InvalidStateTransitionError(
                f"{old.status.value} 상태의 키는 로테이션할 수 없습니다"
            )

        now = utcnow()
        allowed = await repo.list_allowed_models(key_id)

        raw, prefix = vk_policy.generate_key(settings.VIRTUAL_KEY_ENV)
        new = VirtualKey(
            id=uuid.uuid4(),
            name=old.name,
            key_hash=hash_token(raw),
            key_prefix=prefix,
            owner_type=old.owner_type,
            owner_id=old.owner_id,
            team_id=old.team_id,
            status=VKStatus.ACTIVE,
            expires_at=old.expires_at,
            rotated_from_id=old.id,
            created_by=actor.user_id,
        )
        repo.add(new)
        await session.flush()
        await repo.replace_allowed_models(new.id, allowed)

        grace_until = now + timedelta(hours=data.grace_period_hours)
        if data.grace_period_hours == 0:
            # 유예 0 은 즉시 폐기와 같습니다.
            old.status = VKStatus.REVOKED
            old.revoked_at = now
            old.revoked_by = actor.user_id
            old.revoke_reason = vk_policy.RevokeReason.ROTATION.value
        else:
            old.status = VKStatus.ROTATED
            old.expires_at = vk_policy.rotation_expiry(old.expires_at, grace_until=grace_until)

        await audit.record_for(
            session,
            actor,
            action="ROTATE_VIRTUAL_KEY",
            resource_type="virtual_key",
            resource_id=str(new.id),
            changes={
                "before": {"id": str(old.id), "key_prefix": old.key_prefix, "status": old.status.value},
                "after": {
                    "id": str(new.id),
                    "key_prefix": prefix,
                    "grace_period_hours": data.grace_period_hours,
                    "reason": data.reason,
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await self._cache.invalidate(
            [cache_keys.vk_auth(old.key_hash), cache_keys.vk_auth(new.key_hash)]
        )

        await session.refresh(new)
        return VirtualKeyCreateResponse(**_to_response(new, allowed).model_dump(), virtual_key=raw)

    # ── 폐기 ──

    async def revoke(
        self,
        session: AsyncSession,
        *,
        key_id: uuid.UUID,
        reason: vk_policy.RevokeReason,
        note: str | None,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> bool:
        """폐기는 즉시 반영되어야 합니다. 캐시 삭제 성공 여부를 반환합니다."""
        repo = VirtualKeyRepository(session)
        key = await repo.get(key_id, for_update=True)
        if key is None:
            raise NotFoundError("VirtualKey", str(key_id))
        if key.status == VKStatus.REVOKED:
            return True  # 멱등. 재시도 안전.

        before = key.status
        key.status = VKStatus.REVOKED
        key.revoked_at = utcnow()
        key.revoked_by = actor.user_id
        key.revoke_reason = reason.value

        await audit.record_for(
            session,
            actor,
            action="REVOKE_VIRTUAL_KEY",
            resource_type="virtual_key",
            resource_id=str(key_id),
            changes={
                "before": {"status": before.value},
                "after": {"status": VKStatus.REVOKED.value, "reason": reason.value, "note": note},
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        result = await self._cache.invalidate([cache_keys.vk_auth(key.key_hash)])
        if not result.ok:
            logger.warning("virtual_key_service.revoke_cache_not_cleared", key_id=str(key_id))
        return result.ok

    async def revoke_team_keys(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        confirm_team_name: str,
        reason: vk_policy.RevokeReason,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> TeamRevokeAllResponse:
        """사고 대응용 일괄 폐기. 되돌릴 수 없고 client 가 즉시 깨집니다."""
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))
        if confirm_team_name != team.name:
            raise ConflictError(
                "확인용 팀 이름이 일치하지 않습니다", code="confirmation_mismatch"
            )

        hashes = await VirtualKeyRepository(session).revoke_team_keys(
            team_id, actor_id=actor.user_id, reason=reason.value
        )
        await audit.record_for(
            session,
            actor,
            action="REVOKE_TEAM_VIRTUAL_KEYS",
            resource_type="team",
            resource_id=str(team_id),
            changes={"after": {"revoked_count": len(hashes), "reason": reason.value}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        result = await self._cache.invalidate([cache_keys.vk_auth(h) for h in hashes])
        return TeamRevokeAllResponse(
            team_id=str(team_id), revoked_virtual_keys=len(hashes), cache_invalidated=result.ok
        )

    # ── 내부 규칙 ──

    async def _resolve_owner_team(
        self, session: AsyncSession, owner_type: VKOwnerType, owner_id: uuid.UUID
    ) -> uuid.UUID:
        if owner_type == VKOwnerType.TEAM:
            team = await TeamRepository(session).get(owner_id)
            if team is None:
                raise NotFoundError("Team", str(owner_id))
            if not team.is_active:
                raise ValidationError("비활성 팀에는 키를 발급할 수 없습니다", code="team_inactive")
            return team.id

        user = await UserRepository(session).get(owner_id)
        if user is None:
            raise NotFoundError("User", str(owner_id))
        if not user.is_active:
            raise ValidationError("비활성 사용자에게는 키를 발급할 수 없습니다", code="user_inactive")
        if user.team_id is None:
            # 팀 없는 사용량은 예산·rate limit·집계의 어느 축에도 붙지 않습니다.
            raise ValidationError(
                "팀에 배정되지 않은 사용자에게는 키를 발급할 수 없습니다", code="owner_has_no_team"
            )
        return user.team_id

    @staticmethod
    def _validate_expiry(expires_at: datetime, *, max_days: int) -> None:
        now = utcnow()
        if expires_at <= now:
            raise ValidationError("만료 시각은 현재보다 미래여야 합니다", code="expiry_in_past")
        if expires_at > now + timedelta(days=max_days):
            raise ValidationError(
                f"만료 시각은 최대 {max_days}일 이내여야 합니다", code="expiry_too_far"
            )

    @staticmethod
    async def _validate_key_allowlist(
        session: AsyncSession,
        *,
        owner_type: VKOwnerType,
        owner_id: uuid.UUID,
        team_id: uuid.UUID,
        aliases: list[str],
    ) -> list[str]:
        """VK 는 소유자 정책보다 **좁게만** 만들 수 있습니다.

        저장 시점에만 검증합니다. 나중에 소유자 정책이 좁아지면 집행 시점의 교집합이
        자동으로 줄어듭니다(04 문서의 해석 규칙).
        """
        normalized = sorted(set(aliases))
        if not normalized:
            return []

        existing = await ModelAliasRepository(session).exists_all(normalized)
        missing = sorted(set(normalized) - existing)
        if missing:
            raise ValidationError(
                f"카탈로그에 없는 alias 입니다: {', '.join(missing)}",
                code="unknown_model_alias",
                details={"missing": missing},
            )

        allowed_repo = AllowedModelRepository(session)
        owner_allowed: set[str]
        if owner_type == VKOwnerType.USER:
            user_allowed = await allowed_repo.list_for_user(owner_id)
            owner_allowed = set(user_allowed) if user_allowed else set(
                await allowed_repo.list_for_team(team_id)
            )
        else:
            owner_allowed = set(await allowed_repo.list_for_team(team_id))

        # 소유자 정책이 비어 있으면 제한이 없다는 뜻이므로 검사할 상한이 없습니다.
        if owner_allowed:
            outside = sorted(set(normalized) - owner_allowed)
            if outside:
                raise ValidationError(
                    f"소유자 정책에 없는 alias 는 지정할 수 없습니다: {', '.join(outside)}",
                    code="model_not_allowed_for_owner",
                    details={"outside": outside},
                )
        return normalized
