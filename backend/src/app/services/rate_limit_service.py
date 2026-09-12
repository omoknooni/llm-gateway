"""rate limit 설정.

backend 는 **한도를 정의**하고, 집행과 카운팅은 전적으로 gateway 가 합니다(06 문서).
그래서 이 서비스에는 카운터를 쓰는 경로가 없습니다. 예산과 달리 재시드 같은 예외도 없습니다 —
rate limit 카운터를 건드리면 진행 중인 윈도가 리셋되어 한도가 그대로 뚫립니다.

해석 규칙은 `app.policy.rate_limit` 에 순수 함수로 있습니다. 서비스는 후보를 모으고
캐시를 지우는 역할만 합니다.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin, ensure_team_scope
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.deps import RequestContext
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.locks import TeamLock, lock_team
from app.models.enums import RateLimitScope, UserRole, VKOwnerType
from app.models.model import RateLimitConfig
from app.policy import rate_limit as policy
from app.policy.rate_limit import LIMIT_FIELDS, LimitCandidate, Resolution
from app.repositories.model_repository import ModelAliasRepository
from app.repositories.rate_limit_repository import RateLimitRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository
from app.repositories.virtual_key_repository import VirtualKeyRepository
from app.schemas.rate_limits import (
    ConflictingChild,
    EffectiveLimitsResponse,
    RateLimitListResponse,
    RateLimitResponse,
    RateLimitSetRequest,
    RateLimitSetResponse,
    RateLimitTreeMember,
    RateLimitTreeResponse,
    RateLimitUsageResponse,
    ResolvedLimitResponse,
)

logger = structlog.get_logger()

#: gateway 의 집행 카운터 키(`rl:...`) 최종 형태가 Phase 4 미확정입니다. 윈도 표기와
#: cluster mode 용 해시태그(`{}`)가 정해지지 않아 키를 만들 수 없습니다
#: (gateway/docs/README.md "미해결 항목"). 규약이 확정되면 여기서부터 구현합니다.
#: `GLOBAL` 설정은 팀이 없습니다. 직렬화 대상은 여전히 필요하므로 예약 키를 씁니다.
GLOBAL_LOCK_KEY = uuid.UUID(int=0)

COUNTER_CONTRACT_CONFIRMED = False
COUNTER_PENDING_REASON = (
    "gateway 집행 카운터 키 규약이 아직 확정되지 않았습니다(Phase 4). "
    "설정 조회와 변경은 정상 동작합니다."
)


def to_response(config: RateLimitConfig, *, exceeds_parent: bool | None = None) -> RateLimitResponse:
    return RateLimitResponse(
        id=str(config.id),
        scope=config.scope,
        scope_id=str(config.scope_id) if config.scope_id else None,
        model_alias=config.model_alias,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        concurrency_limit=config.concurrency_limit,
        exceeds_parent=exceeds_parent,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _to_candidate(config: RateLimitConfig) -> LimitCandidate:
    return LimitCandidate(
        config_id=config.id,
        scope=config.scope,
        model_scoped=config.model_alias is not None,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        concurrency_limit=config.concurrency_limit,
    )


def _limits_dict(source) -> dict[str, int | None]:
    return {field: getattr(source, field) for field in LIMIT_FIELDS}


def _to_resolved(resolution: Resolution) -> dict[str, ResolvedLimitResponse]:
    return {
        field: ResolvedLimitResponse(
            value=resolution.of(field).value,
            resolved_from=resolution.of(field).resolved_from,
            config_id=resolution.of(field).config_id,
        )
        for field in LIMIT_FIELDS
    }


class RateLimitService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    # ── 설정 ──

    async def set_limit(
        self,
        session: AsyncSession,
        *,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        data: RateLimitSetRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> RateLimitSetResponse:
        """한도 upsert.

        예산과 달리 이전 행을 남기지 않고 제자리에서 갱신합니다. 한도는 "현재 값"이 중요하고
        변경 이력은 감사 로그가 답합니다(부분 unique index 가 활성 행을 하나로 강제합니다).
        """
        team_id = await self._authorize_and_resolve_team(session, scope, scope_id, actor)
        await self._validate_model_alias(session, model_alias)

        # 같은 대상의 upsert 를 직렬화합니다.
        #
        # 예산과 달리 rate limit 에는 **합계 불변식이 없습니다.** 규칙은 "각 하위 ≤ 상위"이고
        # 하위끼리 더해지지 않습니다(600 rpm 팀에 400 rpm 멤버가 둘 있어도 팀 한도는 gateway 가
        # 따로 집행합니다). 그래서 예산 배분 같은 write skew 는 생기지 않습니다.
        #
        # 잠그는 이유는 **upsert 경합**입니다. 행이 없을 때 `SELECT ... FOR UPDATE` 는 잠글
        # 대상이 없어, 같은 조합에 대한 두 요청이 동시에 INSERT 하면 부분 unique index 에서
        # 하나가 터집니다(500). 직렬화하면 뒤의 요청이 UPDATE 경로로 들어옵니다.
        await lock_team(session, team_id or GLOBAL_LOCK_KEY, TeamLock.RATE_LIMIT)

        parent = await self._resolve_parent(session, scope, scope_id, model_alias, team_id=team_id)
        violations = policy.check_within_parent(_limits_dict(data), parent)
        if violations and not actor.is_admin:
            raise ConflictError(
                "상위 scope 의 한도를 넘는 설정입니다",
                code="limit_exceeds_parent",
                details={
                    "violations": [
                        {
                            "field": v.field,
                            "value": v.value,
                            "parent_value": v.parent_value,
                            "parent_resolved_from": v.parent_resolved_from,
                        }
                        for v in violations
                    ]
                },
            )

        repo = RateLimitRepository(session)
        config = await repo.get_active(scope, scope_id, model_alias, for_update=True)
        before = _limits_dict(config) if config is not None else None

        if config is None:
            config = RateLimitConfig(
                id=uuid.uuid4(),
                scope=scope,
                scope_id=scope_id,
                model_alias=model_alias,
                created_by=actor.user_id,
                **_limits_dict(data),
            )
            repo.add(config)
        else:
            for field in LIMIT_FIELDS:
                setattr(config, field, getattr(data, field))

        conflicts = await self._find_conflicting_children(
            session, scope, scope_id, model_alias, _limits_dict(data), team_id=team_id
        )

        await audit.record_for(
            session,
            actor,
            action=f"SET_{scope.value}_RATE_LIMIT",
            resource_type="rate_limit",
            resource_id=f"{scope.value}:{scope_id or 'global'}:{model_alias or '*'}",
            changes={
                "before": before,
                "after": _limits_dict(data),
                # ADMIN 은 상위 초과를 허용받지만, 허용받았다는 사실은 남습니다(06 문서).
                "exceeds_parent": [v.field for v in violations] or None,
                "conflicting_children": len(conflicts) or None,
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(config)

        await self._invalidate(session, scope, scope_id, model_alias)

        return RateLimitSetResponse(
            config=to_response(config, exceeds_parent=bool(violations)),
            conflicting_children=[ConflictingChild(**item) for item in conflicts],
        )

    async def delete_limit(
        self,
        session: AsyncSession,
        *,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> None:
        """정의 전체 제거. `null` 저장과 다릅니다 — 이 층이 아예 없어집니다(06 문서)."""
        team_id = await self._authorize_and_resolve_team(session, scope, scope_id, actor)

        config = await RateLimitRepository(session).get_active(
            scope, scope_id, model_alias, for_update=True
        )
        if config is None:
            raise NotFoundError(
                "RateLimitConfig", f"{scope.value}:{scope_id or 'global'}:{model_alias or '*'}"
            )

        config.is_active = False
        await audit.record_for(
            session,
            actor,
            action=f"DELETE_{scope.value}_RATE_LIMIT",
            resource_type="rate_limit",
            resource_id=f"{scope.value}:{scope_id or 'global'}:{model_alias or '*'}",
            changes={"before": _limits_dict(config), "after": None},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        logger.info("rate_limit.deleted", scope=scope.value, team_id=str(team_id) if team_id else None)
        await self._invalidate(session, scope, scope_id, model_alias)

    # ── 조회 ──

    async def list_limits(
        self,
        session: AsyncSession,
        *,
        scope: RateLimitScope | None,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        actor: CurrentAdmin,
    ) -> RateLimitListResponse:
        if not actor.is_admin:
            visible = await self._visible_scope_ids(session, actor)
            # 권한 밖 대상을 지정하면 빈 목록이 아니라 403 입니다 — 빈 목록이면
            # "설정이 없다"와 "볼 수 없다"를 구분할 수 없습니다(00 문서).
            if scope_id is not None and scope_id not in visible:
                raise ForbiddenError("조회 권한이 없는 대상입니다")

            configs = [
                config
                # 요청한 필터를 그대로 넘깁니다. 떨어뜨리면 권한 범위 전체가 돌아와
                # 목록 필터 계약이 깨집니다.
                for config in await RateLimitRepository(session).list_configs(
                    scope=scope, scope_id=scope_id, model_alias=model_alias
                )
                # 팀장은 자기 팀 축만 봅니다. GLOBAL 은 플랫폼 값이라 함께 보여줍니다 —
                # 자기 한도가 왜 그런지 설명하려면 전역 축이 보여야 합니다.
                if config.scope == RateLimitScope.GLOBAL or config.scope_id in visible
            ]
        else:
            configs = await RateLimitRepository(session).list_configs(
                scope=scope, scope_id=scope_id, model_alias=model_alias
            )

        return RateLimitListResponse(items=[to_response(config) for config in configs])

    async def effective(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None,
        virtual_key_id: uuid.UUID | None,
        model_alias: str | None,
        actor: CurrentAdmin,
    ) -> EffectiveLimitsResponse:
        """해석 결과와 근거.

        두 축을 따로 돌려줍니다. 화면이 "왜 이 한도인가"를 설명하려면 주체 축과 전역 축이
        구분돼야 합니다 — 팀 한도가 낮아도 GLOBAL 에서 먼저 막힐 수 있습니다.
        """
        subject_user, subject_key, team_id = await self._resolve_subject(
            session, user_id, virtual_key_id, actor
        )
        await self._validate_model_alias(session, model_alias)

        configs = await RateLimitRepository(session).list_for_subject(
            team_id=team_id,
            user_id=subject_user,
            virtual_key_id=subject_key,
            model_alias=model_alias,
        )
        subject_axis, global_axis = policy.split_axes([_to_candidate(c) for c in configs])

        return EffectiveLimitsResponse(
            subject={
                "user_id": str(subject_user) if subject_user else None,
                "virtual_key_id": str(subject_key) if subject_key else None,
                "team_id": str(team_id) if team_id else None,
                "model_alias": model_alias,
            },
            effective_limits=_to_resolved(policy.resolve(subject_axis)),
            global_limits=_to_resolved(policy.resolve(global_axis)),
        )

    async def tree(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        model_alias: str | None,
        actor: CurrentAdmin,
    ) -> RateLimitTreeResponse:
        """팀 → 멤버 트리. 상속과 상위 초과를 화면이 그대로 그릴 수 있게 만듭니다."""
        ensure_team_scope(actor, team_id)
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))

        repo = RateLimitRepository(session)
        # 요청한 모델 차원의 후보만 남깁니다. 다른 모델 설정을 섞으면 `model_scoped` 가 더
        # 구체적이라는 이유로 그 값이 이겨, 모델 미지정 조회에 엉뚱한 한도가 나옵니다
        # (팀 전체 600 인데 claude-x 전용 50 이 기본값처럼 보이는 상태).
        team_configs = self._for_dimension(
            await repo.list_configs(scope=RateLimitScope.TEAM, scope_id=team_id), model_alias
        )
        team_config = self._pick_for_alias(team_configs, model_alias)
        team_resolution = policy.resolve([_to_candidate(c) for c in team_configs])

        members = await UserRepository(session).list_by_team(team_id)
        member_configs = self._for_dimension(
            await repo.list_configs(
                scope=RateLimitScope.USER, scope_ids=[member.id for member in members]
            ),
            model_alias,
        )
        by_user: dict[uuid.UUID, list[RateLimitConfig]] = {}
        for config in member_configs:
            by_user.setdefault(config.scope_id, []).append(config)

        entries = []
        for member in members:
            own_configs = by_user.get(member.id, [])
            own = self._pick_for_alias(own_configs, model_alias)
            candidates = [_to_candidate(c) for c in own_configs + team_configs]
            resolution = policy.resolve(candidates)
            exceeds = bool(
                own is not None
                and policy.check_within_parent(_limits_dict(own), team_resolution)
            )
            entries.append(
                RateLimitTreeMember(
                    user_id=str(member.id),
                    display_name=member.display_name,
                    own=to_response(own, exceeds_parent=exceeds) if own else None,
                    effective_limits=_to_resolved(resolution),
                )
            )

        return RateLimitTreeResponse(
            team_id=str(team_id),
            team_name=team.name,
            team_limits=to_response(team_config) if team_config else None,
            members=entries,
        )

    async def usage(
        self,
        session: AsyncSession,
        *,
        scope: RateLimitScope | None,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        actor: CurrentAdmin,
    ) -> RateLimitUsageResponse:
        """실시간 사용률. best-effort 입니다.

        **아직 읽을 수 없습니다.** 집행 카운터 키(`rl:...`)의 최종 형태가 Phase 4 미확정이라
        (윈도 표기, cluster mode 해시태그) 키를 만들 수 없습니다. 규약이 확정되면 여기서
        `cache_keys.rate_limit_counter()` 로 읽습니다.

        엔드포인트를 미리 두는 이유는 이 응답 형태가 **불가용을 정상 상태로 다루도록**
        설계돼 있기 때문입니다(06 문서). 화면은 지금 붙여도 깨지지 않고, 규약 확정 뒤에
        값이 채워집니다.
        """
        if not COUNTER_CONTRACT_CONFIRMED:
            return RateLimitUsageResponse(available=False, reason=COUNTER_PENDING_REASON)

        # 규약 확정 시 이 자리에서 카운터를 읽습니다. 읽기 실패도 오류가 아닙니다 —
        # 관측 기능이 관리 기능을 막으면 안 됩니다.
        raise NotImplementedError

    # ── 내부 ──

    async def _authorize_and_resolve_team(
        self,
        session: AsyncSession,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        actor: CurrentAdmin,
    ) -> uuid.UUID | None:
        """인가와 동시에 이 설정이 속한 팀을 찾습니다.

        팀은 계층 검증의 기준이자 잠금 단위입니다. scope 마다 팀을 찾는 경로가 다릅니다.
        """
        if scope == RateLimitScope.GLOBAL:
            if scope_id is not None:
                raise ValidationError("GLOBAL 한도는 대상 id 를 갖지 않습니다", code="invalid_scope_id")
            if not actor.is_admin:
                raise ForbiddenError("전역 한도는 ADMIN 만 설정할 수 있습니다")
            return None

        if scope_id is None:
            raise ValidationError(f"{scope.value} 한도는 대상 id 가 필요합니다", code="missing_scope_id")

        if scope == RateLimitScope.TEAM:
            team = await TeamRepository(session).get(scope_id)
            if team is None:
                raise NotFoundError("Team", str(scope_id))
            # 팀 한도 자체는 ADMIN 만 바꿉니다. 팀장은 그 안에서 배분만 합니다(06 문서).
            if not actor.is_admin:
                raise ForbiddenError("팀 한도는 ADMIN 만 설정할 수 있습니다")
            return team.id

        if scope == RateLimitScope.USER:
            user = await UserRepository(session).get(scope_id)
            if user is None:
                raise NotFoundError("User", str(scope_id))
            self._require_admin_or_leader_of(actor, user.team_id)
            return user.team_id

        key = await VirtualKeyRepository(session).get(scope_id)
        if key is None:
            raise NotFoundError("VirtualKey", str(scope_id))
        self._require_admin_or_leader_of(actor, key.team_id)
        return key.team_id

    @staticmethod
    def _require_admin_or_leader_of(actor: CurrentAdmin, team_id: uuid.UUID | None) -> None:
        if actor.is_admin:
            return
        if actor.role != UserRole.TEAM_LEADER:
            raise ForbiddenError("rate limit 을 설정할 권한이 없습니다")
        ensure_team_scope(actor, team_id)

    async def _resolve_parent(
        self,
        session: AsyncSession,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        *,
        team_id: uuid.UUID | None,
    ) -> Resolution:
        """상위 scope 의 유효 한도.

        상위란 **덜 구체적인 주체 축**입니다. VK 의 상위는 소유자(USER)와 TEAM, USER 의 상위는
        TEAM 입니다. GLOBAL 은 별도 축이라 상위가 아닙니다 — 주체 한도가 GLOBAL 보다 커도
        GLOBAL 이 함께 집행되므로 모순이 아닙니다.
        """
        if scope in (RateLimitScope.GLOBAL, RateLimitScope.TEAM) or team_id is None:
            return policy.resolve([])

        owner_user_id = None
        if scope == RateLimitScope.VIRTUAL_KEY:
            key = await VirtualKeyRepository(session).get(scope_id)
            # USER 소유 VK 만 사용자 한도를 상위로 갖습니다. TEAM 소유 VK 의 상위는 팀입니다.
            if key is not None and key.owner_type == VKOwnerType.USER:
                owner_user_id = key.owner_id

        configs = await RateLimitRepository(session).list_for_subject(
            team_id=team_id,
            user_id=owner_user_id,
            virtual_key_id=None,
            model_alias=model_alias,
        )
        subject_axis, _ = policy.split_axes([_to_candidate(c) for c in configs])
        return policy.resolve(subject_axis)

    async def _find_conflicting_children(
        self,
        session: AsyncSession,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        limits: dict[str, int | None],
        *,
        team_id: uuid.UUID | None,
    ) -> list[dict]:
        """새 한도보다 큰 하위 설정. 거절하지 않고 목록으로 알립니다(06 문서)."""
        repo = RateLimitRepository(session)

        if scope == RateLimitScope.TEAM and team_id is not None:
            members = await UserRepository(session).list_by_team(team_id)
            children = await repo.list_configs(
                scope=RateLimitScope.USER, scope_ids=[m.id for m in members]
            )
        elif scope == RateLimitScope.USER and scope_id is not None:
            keys = await VirtualKeyRepository(session).list_keys(owner_id=scope_id, limit=200)
            children = await repo.list_configs(
                scope=RateLimitScope.VIRTUAL_KEY, scope_ids=[key.id for key in keys]
            )
        else:
            return []

        same_dimension = [c for c in children if c.model_alias == model_alias]
        return policy.find_conflicting_children(
            limits, [(str(c.scope_id), _limits_dict(c)) for c in same_dimension]
        )

    async def _resolve_subject(
        self,
        session: AsyncSession,
        user_id: uuid.UUID | None,
        virtual_key_id: uuid.UUID | None,
        actor: CurrentAdmin,
    ) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
        """조회 대상과 그 팀. 인가도 함께 판정합니다."""
        if virtual_key_id is not None:
            key = await VirtualKeyRepository(session).get(virtual_key_id)
            if key is None:
                raise NotFoundError("VirtualKey", str(virtual_key_id))

            # 사용자 축은 **키가 말하는 소유자**로만 정합니다. 호출자가 준 user_id 를 그대로
            # 믿으면 두 가지가 깨집니다.
            #   1) 인가 — 자기 user_id 와 남의 key_id 를 섞어 보내면 소유권 검사가 자기
            #      자신으로 통과해 다른 팀 키의 정책까지 보입니다.
            #   2) 정확성 — 실제로 존재하지 않는 (사용자, 키) 조합의 정책 계층을 계산하게 됩니다.
            owner_user_id = key.owner_id if key.owner_type == VKOwnerType.USER else None
            if user_id is not None and user_id != owner_user_id:
                raise ValidationError(
                    "virtual_key_id 의 실제 소유자와 user_id 가 일치하지 않습니다",
                    code="subject_mismatch",
                    details={
                        "virtual_key_id": str(key.id),
                        "owner_user_id": str(owner_user_id) if owner_user_id else None,
                    },
                )

            self._require_can_view_key(actor, owner_user_id, key.team_id)
            return owner_user_id, key.id, key.team_id

        if user_id is not None:
            user = await UserRepository(session).get(user_id)
            if user is None:
                raise NotFoundError("User", str(user_id))
            self._require_can_view(actor, user.id, user.team_id)
            return user.id, None, user.team_id

        # 대상을 지정하지 않으면 자기 자신입니다.
        return actor.user_id, None, actor.team_id

    @staticmethod
    def _require_can_view_key(
        actor: CurrentAdmin, owner_user_id: uuid.UUID | None, team_id: uuid.UUID | None
    ) -> None:
        """VK 조회 인가.

        `_require_can_view` 와 달리 소유권을 **키가 말하는 소유자**와 비교합니다. 호출자가
        보낸 id 로 비교하면 자기 id 를 넣는 것만으로 아무 키나 열립니다.

        `TEAM` 소유 키는 사람에 귀속되지 않으므로 ADMIN 과 그 팀 팀장만 봅니다.
        """
        if actor.is_admin:
            return
        if owner_user_id is not None and actor.user_id == owner_user_id:
            return
        if actor.role == UserRole.TEAM_LEADER:
            ensure_team_scope(actor, team_id)
            return
        raise ForbiddenError("본인 소유 키 또는 상위 권한자만 조회할 수 있습니다")

    @staticmethod
    def _require_can_view(
        actor: CurrentAdmin, user_id: uuid.UUID | None, team_id: uuid.UUID | None
    ) -> None:
        if actor.is_admin or (user_id is not None and actor.user_id == user_id):
            return
        if actor.role == UserRole.TEAM_LEADER:
            ensure_team_scope(actor, team_id)
            return
        raise ForbiddenError("본인 또는 상위 권한자만 조회할 수 있습니다")

    async def _visible_scope_ids(self, session: AsyncSession, actor: CurrentAdmin) -> set[uuid.UUID]:
        if actor.team_id is None:
            raise ForbiddenError("팀에 소속되지 않은 사용자는 조회할 수 없습니다")
        members = await UserRepository(session).list_by_team(actor.team_id)
        keys = await VirtualKeyRepository(session).list_live_for_team(actor.team_id)
        return {actor.team_id, *(m.id for m in members), *(k.id for k in keys)}

    @staticmethod
    def _for_dimension(
        configs: list[RateLimitConfig], model_alias: str | None
    ) -> list[RateLimitConfig]:
        """요청한 모델 차원의 후보만 남깁니다.

        `model_alias` 를 주면 그 모델 행과 전체(NULL) 행이, 주지 않으면 **전체 행만**
        후보입니다. 다른 모델 설정이 섞이면 그것이 더 구체적이라 해석에서 이겨 버립니다.
        `RateLimitRepository.list_for_subject` 가 SQL 로 하는 일과 같은 규칙입니다.
        """
        return [c for c in configs if c.model_alias is None or c.model_alias == model_alias]

    @staticmethod
    def _pick_for_alias(
        configs: list[RateLimitConfig], model_alias: str | None
    ) -> RateLimitConfig | None:
        """그 모델 차원의 설정. 없으면 전체(NULL) 설정입니다."""
        exact = next((c for c in configs if c.model_alias == model_alias), None)
        if exact is not None:
            return exact
        return next((c for c in configs if c.model_alias is None), None)

    @staticmethod
    async def _validate_model_alias(session: AsyncSession, model_alias: str | None) -> None:
        if model_alias is None:
            return
        if not await ModelAliasRepository(session).exists_all([model_alias]):
            raise ValidationError(
                f"카탈로그에 없는 alias 입니다: {model_alias}",
                code="unknown_model_alias",
                details={"model_alias": model_alias},
            )

    async def _invalidate(
        self,
        session: AsyncSession,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
    ) -> None:
        """설정 캐시 삭제.

        `model_alias=NULL` 설정은 **모든 모델에 영향**을 줍니다. gateway 는 요청의 alias 로
        키를 만들어 읽으므로, 그 alias 각각의 키가 낡습니다. 참조 구현처럼 `SCAN` 패턴으로
        지우지 않고 **카탈로그에서 ACTIVE alias 목록을 읽어 정확히** 지웁니다 —
        키스페이스 스캔 비용이 없고 다른 plane 의 키를 지울 위험도 없습니다(06 문서).

        `rl:*` 카운터는 **절대 지우지 않습니다.** 지우면 진행 중인 윈도가 리셋되어 한도가
        그대로 뚫립니다.
        """
        keys = [cache_keys.rate_limit_policy(scope.value, scope_id, model_alias)]
        if model_alias is None:
            aliases = await ModelAliasRepository(session).list_active_aliases()
            keys.extend(
                cache_keys.rate_limit_policy(scope.value, scope_id, alias) for alias in aliases
            )

        result = await self._cache.invalidate(keys, context={"source": "rate_limit_service"})
        if not result.ok:
            logger.warning(
                "rate_limit_service.cache_invalidation_incomplete",
                scope=scope.value,
                failed=result.failed_keys,
            )
