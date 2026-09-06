"""Virtual Key 인증.

client 가 제시한 VK 를 검증해 요청을 **누구의 것으로 볼지** 확정하고, 그 주체가 **어떤 모델을
쓸 수 있는지**까지 한 번에 확정합니다. 산출물은 `AuthContext` 하나이며 이후 모든 단계가
이것만 참조합니다(docs/02).

정상 상태의 요청 경로는 Redis 왕복 한 번으로 끝납니다. DB 는 캐시 miss 일 때만 봅니다.

**fail-closed** 입니다. 확인하지 못한 키는 통과시키지 않습니다. 다만 "확인해 보니 무효"(401)와
"확인할 수 없음"(503)을 구분합니다 — 의존성 장애를 401 로 답하면 client 는 자기 키를 의심하며
멀쩡한 키를 로테이션합니다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.config import Settings
from gateway.core import cache_keys
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.policy.allowed_models import resolve
from gateway.schema.auth import Team, User, VirtualKey, VirtualKeyAllowedModel
from gateway.schema.base import ModelStatus, VKOwnerType, VKStatus
from gateway.schema.model import ModelAlias, TeamAllowedModel, UserAllowedModel

logger = structlog.get_logger(__name__)

#: 인증을 통과할 수 있는 상태 (공유 계약 C1). ROTATED 는 로테이션 유예 동안 살아 있고,
#: 유예는 backend 가 `expires_at` 을 앞당겨 표현하므로 별도 유예 로직이 필요 없습니다.
LIVE_STATUSES = frozenset({VKStatus.ACTIVE, VKStatus.ROTATED})

#: 감사에서 "같은 키가 반복 실패"를 묶기 위한 길이. 32비트로는 원문을 복원할 수 없습니다.
KEY_HASH_PREFIX_LEN = 8


def hash_key(raw_key: str) -> str:
    """공유 계약 C1 의 산출식.

    **해시 알고리즘이나 입력 인코딩을 한쪽만 바꾸면 전 키가 인증 실패합니다.**
    KDF 를 쓰지 않는 것은 의도입니다 — VK 는 사람이 고른 비밀번호가 아니라 256비트 난수라
    사전 공격 대상이 아니고, 해시는 비교용이 아니라 조회 키로 쓰이므로 상수시간 비교 문제도
    발생하지 않습니다.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _invalid(message: str, outcome: AuthOutcome) -> GatewayError:
    """거절 사유를 client 에게 알려주지 않습니다.

    "폐기된 키"와 "없는 키"를 구분해 주면 키 열거에 쓰입니다. 구분은 `auth_events.outcome`
    으로 우리 쪽에만 남깁니다.
    """
    return GatewayError(
        ErrorCode.INVALID_VIRTUAL_KEY, "Invalid virtual key", outcome=outcome
    )


def _unavailable() -> GatewayError:
    return GatewayError(
        ErrorCode.DEPENDENCY_UNAVAILABLE, "Service temporarily unavailable"
    )


def extract_token(authorization: str, api_key: str) -> str:
    """`Authorization: Bearer` 우선, 없으면 `x-api-key`.

    Anthropic client 는 관례적으로 `x-api-key` 를 씁니다. 둘 다 수용하되 우선순위를 고정해
    두 헤더가 다를 때의 동작이 갈리지 않게 합니다.
    """
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    if api_key.strip():
        return api_key.strip()
    raise _invalid("Missing credentials", AuthOutcome.INVALID_KEY)


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def authenticate(
        self,
        *,
        authorization: str,
        api_key: str,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> AuthContext:
        token = extract_token(authorization, api_key)
        key_hash = hash_key(token)
        # 이 지점 이후로 원문은 쓰지 않습니다. 로그·캐시·예외 어디에도 나가지 않습니다.
        del token

        if await self._is_known_miss(redis, key_hash):
            raise _invalid("Known invalid key", AuthOutcome.INVALID_KEY)

        cached = await self._cached_context(redis, key_hash)
        if cached is not None:
            return await self._ensure_live(cached, redis, key_hash)

        if session_factory is None:
            raise _unavailable()

        try:
            async with session_factory() as db:
                context = await self._load(db, key_hash, redis)
        except GatewayError:
            raise
        except SQLAlchemyError as exc:
            # 조회 자체를 못 한 것이지 키가 무효인 것이 아닙니다.
            logger.warning("auth.database_unavailable", error=str(exc))
            raise _unavailable() from exc

        await self._cache(redis, key_hash, context)
        return context

    # ── 캐시 ──

    async def _is_known_miss(self, redis, key_hash: str) -> bool:
        if redis is None:
            return False
        try:
            return await redis.get(cache_keys.vk_miss(key_hash)) is not None
        except Exception:
            return False

    async def _cached_context(self, redis, key_hash: str) -> AuthContext | None:
        if redis is None:
            return None
        try:
            raw = await redis.get(cache_keys.vk_auth(key_hash))
        except Exception as exc:
            logger.warning("auth.cache_read_failed", error=str(exc))
            return None
        if not raw:
            return None
        try:
            return AuthContext.from_json(raw)
        except Exception:
            # 구버전 형식 등 깨진 항목은 예외가 아니라 miss 로 취급해 DB 에서 재구성합니다.
            # 항목 하나가 영구 500 이 되는 것을 막는 방어입니다.
            logger.warning("auth.cache_parse_failed_treated_as_miss")
            return None

    async def _cache(self, redis, key_hash: str, context: AuthContext) -> None:
        if redis is None:
            return
        try:
            await redis.setex(
                cache_keys.vk_auth(key_hash),
                self._settings.vk_auth_ttl_seconds,
                context.to_json(),
            )
        except Exception as exc:
            logger.warning("auth.cache_write_failed", error=str(exc))

    async def _remember_miss(self, redis, key_hash: str) -> None:
        if redis is None:
            return
        with contextlib.suppress(Exception):
            await redis.setex(cache_keys.vk_miss(key_hash), self._settings.vk_miss_ttl_seconds, "1")

    async def _forget(self, redis, key_hash: str) -> None:
        if redis is None:
            return
        with contextlib.suppress(Exception):
            await redis.delete(cache_keys.vk_auth(key_hash))

    async def _ensure_live(self, context: AuthContext, redis, key_hash: str) -> AuthContext:
        """캐시 hit 에도 만료를 다시 봅니다.

        스냅샷은 `expires_at` 을 들고 있으므로 DB 없이 판정할 수 있습니다. 이 검사가 없으면
        캐시된 직후 만료된 키가 TTL(300초) 동안 통과합니다. 로테이션 유예가 `expires_at` 으로
        표현되므로 이건 흔한 경우입니다.
        """
        if context.expires_at is not None and context.expires_at <= datetime.now(UTC):
            # 지우지 않으면 만료된 스냅샷이 TTL 까지 남아 매 요청 같은 판정을 반복합니다.
            await self._forget(redis, key_hash)
            raise _invalid("Key expired", AuthOutcome.EXPIRED)
        return context

    # ── DB ──

    async def _load(self, db: AsyncSession, key_hash: str, redis) -> AuthContext:
        row = (
            await db.execute(
                select(
                    VirtualKey.id,
                    VirtualKey.owner_type,
                    VirtualKey.owner_id,
                    VirtualKey.team_id,
                    VirtualKey.status,
                    VirtualKey.expires_at,
                    User.id.label("user_id"),
                    User.is_active.label("user_active"),
                    Team.is_active.label("team_active"),
                )
                .join(Team, Team.id == VirtualKey.team_id)
                .outerjoin(
                    User,
                    (User.id == VirtualKey.owner_id)
                    & (VirtualKey.owner_type == VKOwnerType.USER),
                )
                .where(VirtualKey.key_hash == key_hash)
            )
        ).one_or_none()

        if row is None:
            await self._remember_miss(redis, key_hash)
            raise _invalid("Unknown key", AuthOutcome.INVALID_KEY)

        if row.status not in LIVE_STATUSES:
            await self._remember_miss(redis, key_hash)
            outcome = (
                AuthOutcome.EXPIRED if row.status == VKStatus.EXPIRED else AuthOutcome.REVOKED
            )
            raise _invalid(f"Key is {row.status}", outcome)

        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            await self._remember_miss(redis, key_hash)
            raise _invalid("Key expired", AuthOutcome.EXPIRED)

        # TEAM 소유 키는 사람이 없으므로 팀 활성만 봅니다.
        owner_active = row.team_active and (
            row.user_active if row.owner_type == VKOwnerType.USER else True
        )
        if not owner_active:
            await self._remember_miss(redis, key_hash)
            raise _invalid("Owner is inactive", AuthOutcome.OWNER_INACTIVE)

        user_id = str(row.user_id) if row.user_id else None
        allowed = await self._resolve_allowed(
            db, redis, virtual_key_id=row.id, team_id=str(row.team_id), user_id=user_id
        )

        return AuthContext(
            virtual_key_id=str(row.id),
            owner_type=str(row.owner_type),
            owner_id=str(row.owner_id),
            team_id=str(row.team_id),
            user_id=user_id,
            status=str(row.status),
            expires_at=row.expires_at,
            allowed_model_aliases=allowed,
        )

    async def _resolve_allowed(
        self, db: AsyncSession, redis, *, virtual_key_id, team_id: str, user_id: str | None
    ) -> tuple[str, ...]:
        """3층 해석 (공유 계약 C3).

        소유자 층 결과는 scope 별로 캐시합니다 — 한 팀의 VK 100개가 같은 팀 목록을 공유하므로,
        대량 무효화 직후에 효과가 큽니다. VK 층은 VK 에 종속이라 `vk:auth` 스냅샷 안에
        최종 결과로만 들어가고 따로 캐시하지 않습니다.
        """
        catalog_active = await self._catalog_active(db, redis)
        team_allowed = await self._scope_allowed(db, redis, "team", team_id)
        user_allowed = (
            await self._scope_allowed(db, redis, "user", user_id) if user_id else ()
        )
        key_allowed = (
            await db.execute(
                select(VirtualKeyAllowedModel.model_alias).where(
                    VirtualKeyAllowedModel.virtual_key_id == virtual_key_id
                )
            )
        ).scalars().all()

        return resolve(
            catalog_active=catalog_active,
            team_allowed=team_allowed,
            user_allowed=user_allowed,
            key_allowed=key_allowed,
        ).aliases

    async def _catalog_active(self, db: AsyncSession, redis) -> tuple[str, ...]:
        cached = await self._cached_list(redis, cache_keys.model_list())
        if cached is not None:
            return cached
        aliases = tuple(
            (
                await db.execute(
                    select(ModelAlias.alias).where(ModelAlias.status == ModelStatus.ACTIVE)
                )
            ).scalars().all()
        )
        await self._cache_list(redis, cache_keys.model_list(), aliases)
        return aliases

    async def _scope_allowed(
        self, db: AsyncSession, redis, scope: str, scope_id: str
    ) -> tuple[str, ...]:
        key = cache_keys.allowed_models(scope, scope_id)
        cached = await self._cached_list(redis, key)
        if cached is not None:
            return cached

        if scope == "team":
            stmt = select(TeamAllowedModel.model_alias).where(TeamAllowedModel.team_id == scope_id)
        else:
            stmt = select(UserAllowedModel.model_alias).where(UserAllowedModel.user_id == scope_id)

        aliases = tuple((await db.execute(stmt)).scalars().all())
        await self._cache_list(redis, key, aliases)
        return aliases

    async def _cached_list(self, redis, key: str) -> tuple[str, ...] | None:
        if redis is None:
            return None
        try:
            raw = await redis.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            return tuple(json.loads(raw))
        except Exception:
            logger.warning("auth.policy_cache_parse_failed_treated_as_miss", key=key)
            return None

    async def _cache_list(self, redis, key: str, values: Iterable[str]) -> None:
        if redis is None:
            return
        with contextlib.suppress(Exception):
            await redis.setex(
                key, self._settings.policy_cache_ttl_seconds, json.dumps(list(values))
            )
