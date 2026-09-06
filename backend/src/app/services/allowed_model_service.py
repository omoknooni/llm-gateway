"""허용 모델 정책.

해석 규칙은 `app.policy.allowed_models` 에 순수 함수로 있습니다. 서비스는 데이터를 모으고
캐시를 지우는 역할만 합니다. 규칙을 두 곳에 두지 않기 위해서입니다.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.deps import RequestContext
from app.core.exceptions import NotFoundError, ValidationError
from app.policy import allowed_models as policy
from app.repositories.model_repository import AllowedModelRepository, ModelAliasRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.repositories.virtual_key_repository import VirtualKeyRepository
from app.schemas.models import AllowedModelsResponse, EffectiveModelsResponse

logger = structlog.get_logger()


class AllowedModelService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    async def get_team_allowed(
        self, session: AsyncSession, team_id: uuid.UUID
    ) -> AllowedModelsResponse:
        await self._require_team(session, team_id)
        aliases = await AllowedModelRepository(session).list_for_team(team_id)
        return AllowedModelsResponse(scope="TEAM", scope_id=str(team_id), model_aliases=aliases)

    async def set_team_allowed(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        aliases: list[str],
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> AllowedModelsResponse:
        """전체 교체. 빈 배열은 팀 층에서 '제한 없음'을 뜻합니다(04 문서)."""
        await self._require_team(session, team_id)
        normalized = await self._validate_aliases(session, aliases)

        repo = AllowedModelRepository(session)
        before = await repo.list_for_team(team_id)
        await repo.replace_for_team(team_id, normalized, actor_id=actor.user_id)

        await audit.record_for(
            session,
            actor,
            action="SET_TEAM_ALLOWED_MODELS",
            resource_type="team",
            resource_id=str(team_id),
            changes={"before": {"model_aliases": before}, "after": {"model_aliases": normalized}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        # 팀 정책이 바뀌면 그 팀 소속 VK 의 인증 컨텍스트가 전부 낡습니다.
        hashes = await VirtualKeyRepository(session).list_live_hashes_for_team(team_id)
        await self._invalidate("team", team_id, hashes)

        return AllowedModelsResponse(scope="TEAM", scope_id=str(team_id), model_aliases=normalized)

    async def get_user_allowed(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> AllowedModelsResponse:
        await self._require_user(session, user_id)
        aliases = await AllowedModelRepository(session).list_for_user(user_id)
        return AllowedModelsResponse(scope="USER", scope_id=str(user_id), model_aliases=aliases)

    async def set_user_allowed(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        aliases: list[str],
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> AllowedModelsResponse:
        """전체 교체. 빈 배열은 사용자 층에서 'override 해제'이지 '전체 허용'이 아닙니다."""
        await self._require_user(session, user_id)
        normalized = await self._validate_aliases(session, aliases)

        repo = AllowedModelRepository(session)
        before = await repo.list_for_user(user_id)
        await repo.replace_for_user(user_id, normalized, actor_id=actor.user_id)

        await audit.record_for(
            session,
            actor,
            action="SET_USER_ALLOWED_MODELS",
            resource_type="user",
            resource_id=str(user_id),
            changes={"before": {"model_aliases": before}, "after": {"model_aliases": normalized}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        hashes = await VirtualKeyRepository(session).list_live_hashes_for_user(user_id)
        await self._invalidate("user", user_id, hashes)

        return AllowedModelsResponse(scope="USER", scope_id=str(user_id), model_aliases=normalized)

    async def resolve_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, *, key_allowed: list[str] | None = None
    ) -> EffectiveModelsResponse:
        """해석 결과와 근거를 함께 돌려줍니다.

        '행 0개'의 의미가 층마다 다르므로, 화면이 근거(`resolved_from`)를 표시해야
        운영자가 왜 이 목록인지 알 수 있습니다.
        """
        user = await self._require_user(session, user_id)
        allowed_repo = AllowedModelRepository(session)

        resolution = policy.resolve(
            catalog_active=await ModelAliasRepository(session).list_active_aliases(),
            team_allowed=await allowed_repo.list_for_team(user.team_id) if user.team_id else [],
            user_allowed=await allowed_repo.list_for_user(user_id),
            key_allowed=key_allowed or [],
        )
        return EffectiveModelsResponse(
            user_id=str(user_id),
            model_aliases=resolution.aliases,
            resolved_from=resolution.resolved_from,
            narrowed_by_key=resolution.narrowed_by_key,
        )

    # ── 내부 ──

    async def _require_team(self, session: AsyncSession, team_id: uuid.UUID):
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))
        return team

    async def _require_user(self, session: AsyncSession, user_id: uuid.UUID):
        user = await UserRepository(session).get(user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return user

    @staticmethod
    async def _validate_aliases(session: AsyncSession, aliases: list[str]) -> list[str]:
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
        return normalized

    async def _invalidate(self, scope: str, scope_id: uuid.UUID, key_hashes: list[str]) -> None:
        keys = [cache_keys.allowed_models(scope, scope_id)]
        keys.extend(cache_keys.vk_auth(key_hash) for key_hash in key_hashes)
        result = await self._cache.invalidate(keys, context={"source": "allowed_model_service"})
        if not result.ok:
            logger.warning(
                "allowed_model_service.cache_invalidation_incomplete", scope=scope, scope_id=str(scope_id)
            )
