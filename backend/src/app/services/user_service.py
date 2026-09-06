"""사용자 관리와 파급 처리.

상태 변경의 표준 순서는 02 문서에 정의되어 있습니다.

    트랜잭션 → 잠금 → 검증 → 변경 → 감사 → **커밋** → 캐시 삭제

커밋 전에 캐시를 지우면, 커밋 사이에 들어온 gateway 요청이 옛 값을 다시 채웁니다.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.config import get_settings
from app.core.deps import RequestContext
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.models.auth import User
from app.models.enums import UserRole
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.repositories.virtual_key_repository import VirtualKeyRepository
from app.schemas.common import Page
from app.schemas.users import (
    OrgTreeMember,
    OrgTreeTeam,
    UserCreateRequest,
    UserDeactivateResponse,
    UserResponse,
    UserTransferResponse,
    UserUpdateRequest,
)

logger = structlog.get_logger()

REVOKE_REASON_DEACTIVATED = "USER_DEACTIVATED"


def to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=str(user.email),
        display_name=user.display_name,
        role=user.role,
        team_id=str(user.team_id) if user.team_id else None,
        provider=user.provider,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class UserService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    async def create(
        self, session: AsyncSession, *, data: UserCreateRequest, actor: CurrentAdmin, ctx: RequestContext
    ) -> UserResponse:
        repo = UserRepository(session)
        email = str(data.email)
        self._check_email_domain(email)

        if await repo.get_by_email(email) is not None:
            raise ConflictError("같은 이메일의 사용자가 이미 있습니다", code="duplicate_email")

        team_id = uuid.UUID(data.team_id) if data.team_id else None
        if team_id is not None:
            await self._require_active_team(session, team_id)

        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name=data.display_name,
            role=data.role,
            team_id=team_id,
        )
        repo.add(user)
        await audit.record_for(
            session,
            actor,
            action="CREATE_USER",
            resource_type="user",
            resource_id=str(user.id),
            changes={"after": {"email": email, "role": data.role.value, "team_id": data.team_id}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(user)
        return to_response(user)

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> UserResponse:
        user = await UserRepository(session).get(user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return to_response(user)

    async def list_users(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[UserResponse]:
        cursor_key = decode_cursor(cursor) if cursor else None
        rows = await UserRepository(session).list_users(
            team_id=team_id,
            role=role,
            is_active=is_active,
            query=query,
            limit=limit + 1,
            cursor_key=cursor_key,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return Page[UserResponse](
            items=[to_response(user) for user in rows], next_cursor=next_cursor, has_more=has_more
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        data: UserUpdateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> UserResponse:
        repo = UserRepository(session)
        user = await repo.get(user_id, for_update=True)
        if user is None:
            raise NotFoundError("User", str(user_id))

        before = {
            "display_name": user.display_name,
            "role": user.role.value,
            "is_active": user.is_active,
        }

        if data.display_name is not None:
            stripped = data.display_name.strip()
            if not stripped:
                raise ValidationError("표시명은 공백만으로 구성될 수 없습니다")
            user.display_name = stripped

        if data.role is not None and data.role != user.role:
            self._guard_self_role_change(actor, user_id)
            await self._guard_last_admin(repo, user, becoming_admin=data.role == UserRole.ADMIN)
            user.role = data.role

        deactivating = data.is_active is False and user.is_active
        if data.is_active is not None and data.is_active != user.is_active:
            if deactivating:
                await self._guard_last_admin(repo, user, becoming_admin=False)
            user.is_active = data.is_active

        revoked_hashes: list[str] = []
        if deactivating:
            # 논리적 오프보딩. 폐기된 사람의 키가 살아남으면 안 됩니다(02 문서).
            revoked_hashes = await VirtualKeyRepository(session).revoke_all_for_owner(
                user_id, actor_id=actor.user_id, reason=REVOKE_REASON_DEACTIVATED
            )

        after = {
            "display_name": user.display_name,
            "role": user.role.value,
            "is_active": user.is_active,
        }
        if revoked_hashes:
            after["revoked_virtual_keys"] = len(revoked_hashes)

        await audit.record_for(
            session,
            actor,
            action="DEACTIVATE_USER" if deactivating else "UPDATE_USER",
            resource_type="user",
            resource_id=str(user.id),
            changes={"before": before, "after": after},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        if revoked_hashes:
            await self._invalidate_user_caches(user_id, revoked_hashes)

        await session.refresh(user)
        return to_response(user)

    async def deactivate(
        self, session: AsyncSession, *, user_id: uuid.UUID, actor: CurrentAdmin, ctx: RequestContext
    ) -> UserDeactivateResponse:
        """비활성화 전용 경로. 폐기된 VK 수와 캐시 반영 여부를 응답에 드러냅니다."""
        repo = UserRepository(session)
        user = await repo.get(user_id, for_update=True)
        if user is None:
            raise NotFoundError("User", str(user_id))
        if not user.is_active:
            return UserDeactivateResponse(
                user_id=str(user_id), revoked_virtual_keys=0, cache_invalidated=True
            )

        self._guard_self_role_change(actor, user_id)
        await self._guard_last_admin(repo, user, becoming_admin=False)

        user.is_active = False
        revoked_hashes = await VirtualKeyRepository(session).revoke_all_for_owner(
            user_id, actor_id=actor.user_id, reason=REVOKE_REASON_DEACTIVATED
        )
        await audit.record_for(
            session,
            actor,
            action="DEACTIVATE_USER",
            resource_type="user",
            resource_id=str(user_id),
            changes={
                "before": {"is_active": True},
                "after": {"is_active": False, "revoked_virtual_keys": len(revoked_hashes)},
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        result = await self._invalidate_user_caches(user_id, revoked_hashes)
        return UserDeactivateResponse(
            user_id=str(user_id),
            revoked_virtual_keys=len(revoked_hashes),
            cache_invalidated=result,
        )

    async def transfer_team(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        team_id: uuid.UUID | None,
        reason: str | None,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> UserTransferResponse:
        """팀 이동.

        VK 를 폐기하지 않습니다. VK 는 사람에 귀속되고 팀은 그 사람의 속성이기 때문입니다.
        다만 gateway 캐시에 옛 team_id 가 들어 있으므로, 커밋 직후 그 사용자 소유 VK 전부의
        캐시를 지웁니다. 이 삭제가 빠지면 새 팀의 예산·rate limit 이 TTL 만큼 늦게 적용됩니다.

        과거 사용량은 옛 팀에 남습니다. `usage_events` 에 기록 시점 team_id 가 이미 박혀
        있으므로 소급 재작성하지 않습니다.
        """
        repo = UserRepository(session)
        user = await repo.get(user_id, for_update=True)
        if user is None:
            raise NotFoundError("User", str(user_id))

        previous_team_id = user.team_id
        if team_id is not None:
            await self._require_active_team(session, team_id)

        user.team_id = team_id
        vk_repo = VirtualKeyRepository(session)
        if team_id is not None:
            affected_hashes = await vk_repo.move_owner_keys_to_team(user_id, team_id)
        else:
            # 팀이 없으면 VK 의 team_id 를 채울 수 없습니다. 소유 키를 폐기합니다.
            affected_hashes = await vk_repo.revoke_all_for_owner(
                user_id, actor_id=actor.user_id, reason="TEAM_UNASSIGNED"
            )

        await audit.record_for(
            session,
            actor,
            action="TRANSFER_USER_TEAM",
            resource_type="user",
            resource_id=str(user_id),
            changes={
                "before": {"team_id": str(previous_team_id) if previous_team_id else None},
                "after": {
                    "team_id": str(team_id) if team_id else None,
                    "affected_virtual_keys": len(affected_hashes),
                    "reason": reason,
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        invalidated = await self._invalidate_user_caches(user_id, affected_hashes)
        return UserTransferResponse(
            user_id=str(user_id),
            team_id=str(team_id) if team_id else None,
            previous_team_id=str(previous_team_id) if previous_team_id else None,
            affected_virtual_keys=len(affected_hashes),
            cache_invalidated=invalidated,
        )

    async def org_tree(self, session: AsyncSession) -> list[OrgTreeTeam]:
        """화면 전용 집계. 팀 수 × 멤버 수의 N+1 을 피하려고 2회 쿼리로 조립합니다."""
        teams = await TeamRepository(session).list_all_active()
        members_by_team: dict[uuid.UUID, list[OrgTreeMember]] = {}
        for team in teams:
            members_by_team[team.id] = []

        users = await UserRepository(session).list_users(limit=10_000)
        for user in users:
            if user.team_id in members_by_team:
                members_by_team[user.team_id].append(
                    OrgTreeMember(
                        id=str(user.id),
                        display_name=user.display_name,
                        email=str(user.email),
                        role=user.role,
                        is_active=user.is_active,
                    )
                )

        return [
            OrgTreeTeam(
                id=str(team.id),
                name=team.name,
                is_active=team.is_active,
                leader_user_id=str(team.leader_user_id) if team.leader_user_id else None,
                members=members_by_team[team.id],
            )
            for team in teams
        ]

    # ── 내부 규칙 ──

    def _check_email_domain(self, email: str) -> None:
        allowed = get_settings().ALLOWED_EMAIL_DOMAINS
        if not allowed:
            return
        domain = email.rsplit("@", 1)[-1].lower()
        if domain not in {item.lower() for item in allowed}:
            raise ValidationError(f"허용되지 않은 이메일 도메인입니다: {domain}")

    @staticmethod
    def _guard_self_role_change(actor: CurrentAdmin, user_id: uuid.UUID) -> None:
        """자기 권한을 자기가 내리는 자해를 막습니다."""
        if actor.user_id == user_id:
            raise ConflictError(
                "자기 자신의 역할과 활성 상태는 변경할 수 없습니다", code="cannot_modify_self_role"
            )

    @staticmethod
    async def _guard_last_admin(repo: UserRepository, user: User, *, becoming_admin: bool) -> None:
        """마지막 활성 ADMIN 을 잃으면 복구 경로가 부트스트랩 재실행뿐입니다."""
        if becoming_admin or user.role != UserRole.ADMIN or not user.is_active:
            return
        if await repo.count_active_admins(excluding=user.id) == 0:
            raise ConflictError(
                "마지막 활성 ADMIN 은 강등하거나 비활성화할 수 없습니다", code="last_admin_protected"
            )

    async def _require_active_team(self, session: AsyncSession, team_id: uuid.UUID) -> None:
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))
        if not team.is_active:
            raise ValidationError("비활성 팀에는 사용자를 배정할 수 없습니다", code="team_inactive")

    async def _invalidate_user_caches(self, user_id: uuid.UUID, key_hashes: list[str]) -> bool:
        """커밋 이후 호출합니다. 실패해도 요청을 되돌리지 않습니다."""
        keys = [cache_keys.vk_auth(key_hash) for key_hash in key_hashes]
        keys.append(cache_keys.allowed_models("user", user_id))
        result = await self._cache.invalidate(keys, context={"source": "user_service"})
        if not result.ok:
            logger.warning("user_service.cache_invalidation_incomplete", user_id=str(user_id))
        return result.ok
