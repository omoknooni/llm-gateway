"""예산 관리.

경계가 이 서비스의 전부입니다. **집행은 gateway 가 하고 backend 는 정책과 가시성을
소유합니다**(05 문서). 따라서 여기서는

- `budget.budget_configs` 를 쓰고,
- `policy:budget:*` 캐시를 **지우기만** 하고,
- `budget:usage:*` 카운터는 **읽기만** 합니다.

카운터를 쓰는 경로는 `reseed` 하나뿐이고, 그것이 예외임을 이름과 권한(ADMIN)으로 드러냅니다.

판정 규칙은 `app.policy.budget` 에 순수 함수로 있습니다. 서비스는 데이터를 모으는 역할입니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin, ensure_team_scope
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.clock import month_period, utcnow
from app.core.deps import RequestContext
from app.core.exceptions import (
    ConflictError,
    CounterWriteError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.locks import lock_team_budget
from app.models.auth import Team, User
from app.models.budget import BudgetConfig
from app.models.enums import BudgetPolicy, BudgetScope, UserRole
from app.policy import budget as policy
from app.policy.usage import NO_USER_ID, NO_USER_LABEL
from app.repositories.budget_repository import BudgetConfigRepository, BudgetUsageRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.usage_repository import UsageAggregateRepository, UsageBreakdownRow
from app.repositories.user_repository import UserRepository
from app.schemas.budgets import (
    AllocationEntry,
    AllocationResponse,
    AllocationSetRequest,
    BudgetConfigResponse,
    BudgetSetRequest,
    BudgetSummaryResponse,
    BudgetUsageItem,
    MyBudgetResponse,
    ReseedRequest,
    ReseedResponse,
    ReseedResultItem,
    TeamBudgetUsageResponse,
    UnsetBudgetResponse,
    UnsetBudgetTarget,
    UsageBreakdownItem,
    UserBudgetUsageResponse,
)

logger = structlog.get_logger()

SOURCE_REDIS = "redis"
SOURCE_DB = "db"
SOURCE_MIXED = "mixed"

ZERO = Decimal("0")

#: 예산 미설정 항목의 표시용 정책. 집행은 "설정 없음 = 통과"이므로 차단 정책을 붙이지 않습니다.
UNLIMITED_POLICY = BudgetPolicy.SOFT_WARN


def to_config_response(config: BudgetConfig) -> BudgetConfigResponse:
    return BudgetConfigResponse(
        id=str(config.id),
        scope=config.scope,
        scope_id=str(config.scope_id),
        limit_usd=config.limit_usd,
        period_type=config.period_type,
        policy=config.policy,
        warn_thresholds=list(config.warn_thresholds),
        effective_from=config.effective_from,
        is_active=config.is_active,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _snapshot(config: BudgetConfig | None) -> dict | None:
    if config is None:
        return None
    return {
        "limit_usd": str(config.limit_usd),
        "policy": config.policy.value,
        "warn_thresholds": list(config.warn_thresholds),
        "effective_from": config.effective_from.isoformat(),
    }


@dataclass(frozen=True)
class ResolvedUsage:
    used_usd: Decimal
    source: str


class UsageReader:
    """소진값 읽기. **Redis 우선, 없으면 DB**(05 문서).

    운영자가 보는 숫자는 집행에 쓰이는 숫자와 같아야 합니다. 그래서 내구 사본이 아니라
    카운터를 먼저 봅니다. 월 경계 직후 키가 없는 것은 정상이고 0 에서 시작합니다.

    Redis 장애는 조회를 실패시키지 않습니다. DB 로 떨어지되 `source` 로 드러냅니다 —
    조용히 대체하면 운영자가 "왜 숫자가 집행과 다른가"를 알 수 없습니다.
    """

    def __init__(self, redis: aioredis.Redis, session: AsyncSession) -> None:
        self._redis = redis
        self._session = session

    async def read_many(
        self, scope: BudgetScope, scope_ids: list[uuid.UUID], period: str
    ) -> dict[uuid.UUID, ResolvedUsage]:
        if not scope_ids:
            return {}

        db_rows = await BudgetUsageRepository(self._session).map_for(scope, scope_ids, period)
        counters = await self.read_counters(scope, scope_ids, period)

        resolved: dict[uuid.UUID, ResolvedUsage] = {}
        for scope_id in scope_ids:
            counter = counters.get(scope_id)
            if counter is not None:
                resolved[scope_id] = ResolvedUsage(counter, SOURCE_REDIS)
                continue
            row = db_rows.get(scope_id)
            resolved[scope_id] = ResolvedUsage(row.used_usd if row else ZERO, SOURCE_DB)
        return resolved

    async def read(self, scope: BudgetScope, scope_id: uuid.UUID, period: str) -> ResolvedUsage:
        return (await self.read_many(scope, [scope_id], period))[scope_id]

    async def read_counters(
        self, scope: BudgetScope, scope_ids: list[uuid.UUID], period: str
    ) -> dict[uuid.UUID, Decimal]:
        """카운터 원값. **키가 없는 것과 0 을 구분해야 하는 호출자**(정합성 검증 job)를 위해
        `read_many` 와 달리 DB 폴백 없이 있는 것만 돌려줍니다."""
        keys = [cache_keys.budget_usage_counter(scope.value, scope_id, period) for scope_id in scope_ids]
        try:
            raw_values = await self._redis.mget(keys)
        except Exception as exc:
            logger.warning("budget.counter_read_failed", scope=scope.value, error=str(exc))
            return {}

        counters: dict[uuid.UUID, Decimal] = {}
        for scope_id, raw in zip(scope_ids, raw_values, strict=True):
            if raw is None:
                continue
            try:
                counters[scope_id] = policy.quantize_money(Decimal(raw))
            except (InvalidOperation, ValueError):
                # 손상된 값은 없는 것으로 보고 DB 로 떨어뜨립니다. 여기서 지우면 집행 상태가 풀립니다.
                logger.warning("budget.counter_unparsable", scope=scope.value, scope_id=str(scope_id))
        return counters


class BudgetService:
    def __init__(self, cache_mgr: CacheInvalidationManager, redis: aioredis.Redis) -> None:
        self._cache = cache_mgr
        self._redis = redis

    # ── 설정 ──

    async def set_team_budget(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        data: BudgetSetRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> BudgetConfigResponse:
        await self._require_team(session, team_id)
        await lock_team_budget(session, team_id)

        allocated = await self._allocated_total(session, team_id)
        if allocated > data.limit_usd:
            # 팀 한도를 이미 배분된 합계보다 낮추면 하위 합이 상위를 넘습니다.
            raise ConflictError(
                "이미 배분된 사용자 예산 합계보다 낮은 팀 한도는 설정할 수 없습니다",
                code="budget_limit_conflict",
                details={
                    "team_id": str(team_id),
                    "allocated_usd": str(allocated),
                    "limit_usd": str(data.limit_usd),
                },
            )

        before, config = await self._upsert_config(
            session, BudgetScope.TEAM, team_id, data, actor=actor
        )
        await audit.record_for(
            session,
            actor,
            action="SET_TEAM_BUDGET",
            resource_type="team",
            resource_id=str(team_id),
            changes={"before": before, "after": _snapshot(config)},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(config)

        await self._invalidate([cache_keys.budget_policy(BudgetScope.TEAM.value, team_id)])
        return to_config_response(config)

    async def clear_team_budget(
        self, session: AsyncSession, *, team_id: uuid.UUID, actor: CurrentAdmin, ctx: RequestContext
    ) -> None:
        """해제 = 무제한. 새 행을 만들지 않고 활성 행을 닫습니다.

        팀 잠금을 잡지 않습니다. 해제는 제약을 **없애는** 방향이라 동시 실행이 배분 불변식
        (사용자 합계 ≤ 팀 한도)을 깰 수 없습니다.
        """
        await self._require_team(session, team_id)
        config = await BudgetConfigRepository(session).get_active(
            BudgetScope.TEAM, team_id, for_update=True
        )
        if config is None:
            raise NotFoundError("TeamBudget", str(team_id))

        config.is_active = False
        await audit.record_for(
            session,
            actor,
            action="CLEAR_TEAM_BUDGET",
            resource_type="team",
            resource_id=str(team_id),
            changes={"before": _snapshot(config), "after": None},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        await self._invalidate([cache_keys.budget_policy(BudgetScope.TEAM.value, team_id)])

    async def set_user_budget(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        data: BudgetSetRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> BudgetConfigResponse:
        user = await self._require_user(session, user_id)
        self._ensure_can_manage_user_budget(actor, user)
        if user.team_id is not None:
            await lock_team_budget(session, user.team_id)
        await self._ensure_within_team_limit(session, user, new_limit=data.limit_usd)

        before, config = await self._upsert_config(
            session, BudgetScope.USER, user_id, data, actor=actor
        )
        await audit.record_for(
            session,
            actor,
            action="SET_USER_BUDGET",
            resource_type="user",
            resource_id=str(user_id),
            changes={"before": before, "after": _snapshot(config)},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()
        await session.refresh(config)

        await self._invalidate([cache_keys.budget_policy(BudgetScope.USER.value, user_id)])
        return to_config_response(config)

    async def clear_user_budget(
        self, session: AsyncSession, *, user_id: uuid.UUID, actor: CurrentAdmin, ctx: RequestContext
    ) -> None:
        """배분 해제. 합계를 **줄이는** 방향이라 팀 잠금이 필요 없습니다."""
        user = await self._require_user(session, user_id)
        self._ensure_can_manage_user_budget(actor, user)

        config = await BudgetConfigRepository(session).get_active(
            BudgetScope.USER, user_id, for_update=True
        )
        if config is None:
            raise NotFoundError("UserBudget", str(user_id))

        config.is_active = False
        await audit.record_for(
            session,
            actor,
            action="CLEAR_USER_BUDGET",
            resource_type="user",
            resource_id=str(user_id),
            changes={"before": _snapshot(config), "after": None},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        await self._invalidate([cache_keys.budget_policy(BudgetScope.USER.value, user_id)])

    # ── 배분 ──

    async def get_allocation(
        self, session: AsyncSession, *, team_id: uuid.UUID, period: str | None = None
    ) -> AllocationResponse:
        await self._require_team(session, team_id)
        period = period or month_period()

        team_config = await BudgetConfigRepository(session).get_active(BudgetScope.TEAM, team_id)
        team_limit = team_config.limit_usd if team_config else ZERO

        members = await UserRepository(session).list_by_team(team_id)
        member_by_id = {member.id: member for member in members}
        configs = await BudgetConfigRepository(session).list_active(
            BudgetScope.USER, list(member_by_id)
        )
        usages = await UsageReader(self._redis, session).read_many(
            BudgetScope.USER, [config.scope_id for config in configs], period
        )

        entries = []
        for config in sorted(configs, key=lambda c: member_by_id[c.scope_id].display_name):
            member = member_by_id[config.scope_id]
            usage = usages[config.scope_id]
            entries.append(
                AllocationEntry(
                    user_id=str(member.id),
                    display_name=member.display_name,
                    email=member.email,
                    limit_usd=config.limit_usd,
                    used_usd=usage.used_usd,
                    usage_pct=policy.usage_pct(usage.used_usd, config.limit_usd),
                    alert_level=policy.alert_level(
                        usage.used_usd, config.limit_usd, config.warn_thresholds
                    ),
                    source=usage.source,
                )
            )

        check = policy.check_allocation(team_limit, [config.limit_usd for config in configs])
        return AllocationResponse(
            team_id=str(team_id),
            period=period,
            team_limit_usd=team_limit,
            allocated_usd=check.allocated_usd,
            unallocated_usd=check.unallocated_usd,
            allocations=entries,
        )

    async def set_allocation(
        self,
        session: AsyncSession,
        *,
        team_id: uuid.UUID,
        data: AllocationSetRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> AllocationResponse:
        """배분 일괄 설정. **전체 교체이고 원자적**입니다(05 문서).

        하나라도 검증에 실패하면 전체를 롤백합니다. 부분 적용은 합계가 한도를 넘은 중간
        상태를 남깁니다.
        """
        await self._require_team(session, team_id)
        ensure_team_scope(actor, team_id)
        await lock_team_budget(session, team_id)

        config_repo = BudgetConfigRepository(session)
        team_config = await config_repo.get_active(BudgetScope.TEAM, team_id)
        if team_config is None:
            # 상한이 없는데 배분하면 검증할 기준이 없습니다. 무제한의 배분은 배분이 아닙니다.
            raise ConflictError(
                "팀 예산이 설정되지 않아 배분할 수 없습니다", code="team_budget_not_set"
            )

        members = {member.id: member for member in await UserRepository(session).list_by_team(team_id)}
        unknown = [str(item.user_id) for item in data.allocations if item.user_id not in members]
        if unknown:
            raise ValidationError(
                "팀 소속이 아닌 사용자에게는 배분할 수 없습니다",
                code="user_not_in_team",
                details={"user_ids": unknown},
            )
        inactive = [
            str(item.user_id) for item in data.allocations if not members[item.user_id].is_active
        ]
        if inactive:
            raise ValidationError(
                "비활성 사용자에게는 배분할 수 없습니다",
                code="user_inactive",
                details={"user_ids": inactive},
            )

        check = policy.check_allocation(
            team_config.limit_usd, [item.limit_usd for item in data.allocations]
        )
        if check.exceeds:
            raise ConflictError(
                "배분 합계가 팀 예산을 초과합니다",
                code="allocation_exceeds_team_budget",
                details={
                    "team_id": str(team_id),
                    "allocated_usd": str(check.allocated_usd),
                    "limit_usd": str(team_config.limit_usd),
                },
            )

        requested = {item.user_id: item.limit_usd for item in data.allocations}
        existing = await config_repo.list_active(BudgetScope.USER, list(members))
        before = {str(config.scope_id): str(config.limit_usd) for config in existing}

        touched: list[uuid.UUID] = []
        for config in existing:
            if config.scope_id not in requested:
                # 목록에 없는 멤버는 배분 해제입니다(전체 교체).
                config.is_active = False
                touched.append(config.scope_id)
        await session.flush()

        for user_id, limit_usd in requested.items():
            await self._upsert_config(
                session,
                BudgetScope.USER,
                user_id,
                BudgetSetRequest(
                    limit_usd=limit_usd,
                    policy=data.policy,
                    warn_thresholds=data.warn_thresholds,
                ),
                actor=actor,
            )
            touched.append(user_id)

        await audit.record_for(
            session,
            actor,
            action="SET_TEAM_BUDGET_ALLOCATION",
            resource_type="team",
            resource_id=str(team_id),
            changes={
                "before": {"allocations": before},
                "after": {
                    "allocations": {str(uid): str(amount) for uid, amount in requested.items()},
                    "team_limit_usd": str(team_config.limit_usd),
                    "unallocated_usd": str(check.unallocated_usd),
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await session.commit()

        await self._invalidate(
            [cache_keys.budget_policy(BudgetScope.USER.value, user_id) for user_id in set(touched)]
        )
        return await self.get_allocation(session, team_id=team_id)

    # ── 조회 ──

    async def summary(
        self,
        session: AsyncSession,
        *,
        scope: BudgetScope,
        period: str | None,
        actor: CurrentAdmin,
    ) -> BudgetSummaryResponse:
        period = period or month_period()
        config_repo = BudgetConfigRepository(session)

        if scope == BudgetScope.TEAM:
            scope_ids = None if actor.is_admin else [self._own_team(actor)]
            configs = await config_repo.list_active(BudgetScope.TEAM, scope_ids)
            names = await self._team_names(session, [config.scope_id for config in configs])
        else:
            if actor.is_admin:
                scope_ids = None
            else:
                members = await UserRepository(session).list_by_team(self._own_team(actor))
                scope_ids = [member.id for member in members]
            configs = await config_repo.list_active(BudgetScope.USER, scope_ids)
            names = await self._user_names(session, [config.scope_id for config in configs])

        items = await self._usage_items(session, scope, configs, names, period)
        return BudgetSummaryResponse(period=period, source=_combined_source(items), items=items)

    async def team_usage(
        self, session: AsyncSession, *, team_id: uuid.UUID, period: str | None = None
    ) -> TeamBudgetUsageResponse:
        team = await self._require_team(session, team_id)
        period = period or month_period()

        config = await BudgetConfigRepository(session).get_active(BudgetScope.TEAM, team_id)
        item = await self._single_item(session, BudgetScope.TEAM, team_id, team.name, config, period)

        usage_repo = UsageAggregateRepository(session)
        by_member = await usage_repo.team_breakdown_by_user(team_id, period)
        member_names = await self._user_names(
            session, [uuid.UUID(row.key) for row in by_member if _is_uuid(row.key)]
        )
        # 팀 공용 VK 호출은 사람에 귀속되지 않아 집계에 예약 UUID 로 모입니다(M7). 비용이 실린
        # 행이 이름 없이 남으면 읽는 사람이 원인을 못 찾으므로 라벨을 답니다.
        member_names[NO_USER_ID] = NO_USER_LABEL
        return TeamBudgetUsageResponse(
            period=period,
            budget=item,
            by_member=_to_breakdown(by_member, member_names),
            by_model=_to_breakdown(await usage_repo.team_breakdown_by_model(team_id, period), {}),
        )

    async def user_usage(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        actor: CurrentAdmin,
        period: str | None = None,
    ) -> UserBudgetUsageResponse:
        user = await self._require_user(session, user_id)
        self._ensure_can_view_user_budget(actor, user)
        period = period or month_period()

        config = await BudgetConfigRepository(session).get_active(BudgetScope.USER, user_id)
        item = await self._single_item(
            session, BudgetScope.USER, user_id, user.display_name, config, period
        )
        rows = await UsageAggregateRepository(session).user_breakdown_by_model(user_id, period)
        return UserBudgetUsageResponse(period=period, budget=item, by_model=_to_breakdown(rows, {}))

    async def my_budget(
        self, session: AsyncSession, *, actor: CurrentAdmin, period: str | None = None
    ) -> MyBudgetResponse:
        """내 예산과 소진율. 사용자 예산과 팀 예산을 **함께** 돌려줍니다.

        둘 다 집행에 쓰이므로(사용자 예산이 남아도 팀이 소진되면 차단) 한쪽만 보여주면
        차단 이유를 화면에서 설명할 수 없습니다.
        """
        period = period or month_period()
        config_repo = BudgetConfigRepository(session)

        user_item = None
        user_config = await config_repo.get_active(BudgetScope.USER, actor.user_id)
        if user_config is not None:
            user_item = await self._single_item(
                session, BudgetScope.USER, actor.user_id, actor.email, user_config, period
            )

        team_item = None
        if actor.team_id is not None:
            team_config = await config_repo.get_active(BudgetScope.TEAM, actor.team_id)
            if team_config is not None:
                team = await TeamRepository(session).get(actor.team_id)
                team_item = await self._single_item(
                    session,
                    BudgetScope.TEAM,
                    actor.team_id,
                    team.name if team else None,
                    team_config,
                    period,
                )

        return MyBudgetResponse(period=period, user=user_item, team=team_item)

    async def unset_budgets(
        self, session: AsyncSession, *, team_id: uuid.UUID | None = None
    ) -> UnsetBudgetResponse:
        """예산 미설정 목록.

        미설정은 무제한입니다. 이 목록이 보이지 않으면 "설정을 빠뜨린 것"과 "일부러 무제한인 것"이
        구분되지 않습니다(05 문서).
        """
        repo = BudgetConfigRepository(session)
        teams = [] if team_id is not None else await repo.teams_without_budget()
        users = await repo.users_without_budget(team_id=team_id)
        return UnsetBudgetResponse(
            teams=[UnsetBudgetTarget(id=str(team.id), name=team.name) for team in teams],
            users=[
                UnsetBudgetTarget(
                    id=str(user.id),
                    name=user.display_name,
                    team_id=str(user.team_id) if user.team_id else None,
                )
                for user in users
            ],
        )

    # ── 재시드(운영 예외) ──

    async def reseed(
        self, session: AsyncSession, *, data: ReseedRequest, actor: CurrentAdmin, ctx: RequestContext
    ) -> ReseedResponse:
        """소진값 재시드.

        control plane 이 집행 카운터를 쓰는 **유일한 경로**입니다. 자동 경로가 아니라 사람이
        명시적으로 호출하는 복구 도구이기 때문에 허용합니다(05 문서).

        Redis 와 DB 를 함께 갱신합니다. 두 저장소에 걸친 갱신이라 원자적으로 만들 수는 없고,
        **실패했을 때 어느 쪽이 남는지**를 고를 수 있을 뿐입니다. 순서는

        1. DB 변경을 트랜잭션에 쌓습니다(커밋하지 않음).
        2. 카운터 전체를 **파이프라인 한 번**으로 씁니다. 실패하면 트랜잭션을 되돌리고
           503 으로 거절합니다 — 아무것도 바뀌지 않습니다.
        3. 커밋합니다.

        커밋이 실패하면 카운터만 새 값으로 남습니다. 이쪽이 덜 나쁩니다 — 집행은 운영자가
        의도한 값을 쓰게 되고, 어긋난 내구 사본은 `verify_budget_counters` 가 drift 로
        잡아냅니다. 반대 순서(커밋 먼저)는 Redis 가 실패했을 때 **집행이 옛 값을 계속 쓰는
        상태**가 조용히 남습니다.
        """
        usage_repo = BudgetUsageRepository(session)
        config_repo = BudgetConfigRepository(session)

        results: list[tuple[BudgetScope, uuid.UUID, str, Decimal | None, Decimal]] = []
        for item in data.items:
            await self._require_scope_target(session, item.scope, item.scope_id)

            row = await usage_repo.get(item.scope, item.scope_id, item.period, for_update=True)
            before = row.used_usd if row is not None else None
            if row is None:
                config = await config_repo.get_active(item.scope, item.scope_id)
                usage_repo.add(
                    scope=item.scope,
                    scope_id=item.scope_id,
                    period=item.period,
                    used_usd=item.used_usd,
                    limit_usd=config.limit_usd if config else ZERO,
                )
            else:
                row.used_usd = item.used_usd
            results.append((item.scope, item.scope_id, item.period, before, item.used_usd))

        # 항목마다 한 건씩 남깁니다. 한 건으로 묶으면 "이 팀의 소진값을 누가 고쳤는가" 를
        # resource_id 로 찾을 수 없게 됩니다(00 문서 Audit Contract).
        for scope, scope_id, period, before, after in results:
            await audit.record_for(
                session,
                actor,
                action="RESEED_BUDGET_USAGE",
                resource_type="budget_usage",
                resource_id=f"{scope.value}:{scope_id}:{period}",
                changes={
                    "reason": data.reason,
                    "before": {"used_usd": str(before) if before is not None else None},
                    "after": {"used_usd": str(after)},
                },
                ip_address=ctx.ip_address,
                request_id=ctx.request_id,
            )
        await session.flush()

        written = await self._write_counters(
            [(scope, scope_id, period, after) for scope, scope_id, period, _, after in results]
        )
        if not written:
            await session.rollback()
            raise CounterWriteError(
                "집행 카운터를 갱신하지 못해 재시드를 취소했습니다",
                details={"items": len(results)},
            )

        await session.commit()
        return ReseedResponse(
            items=[
                ReseedResultItem(
                    scope=scope,
                    scope_id=str(scope_id),
                    period=period,
                    before_usd=before,
                    after_usd=after,
                )
                for scope, scope_id, period, before, after in results
            ]
        )

    # ── 내부 ──

    async def _upsert_config(
        self,
        session: AsyncSession,
        scope: BudgetScope,
        scope_id: uuid.UUID,
        data: BudgetSetRequest,
        *,
        actor: CurrentAdmin,
    ) -> tuple[dict | None, BudgetConfig]:
        """이전 행을 닫고 새 행을 추가합니다.

        UPDATE 로 덮으면 "언제 누가 한도를 올렸는가"가 남지 않습니다(05 문서). 활성 행은
        부분 unique index 로 scope 당 하나이므로, 닫은 뒤 **flush 하고** 새 행을 넣습니다.
        """
        repo = BudgetConfigRepository(session)
        current = await repo.get_active(scope, scope_id, for_update=True)
        before = _snapshot(current)
        if current is not None:
            current.is_active = False
            await session.flush()

        config = BudgetConfig(
            id=uuid.uuid4(),
            scope=scope,
            scope_id=scope_id,
            limit_usd=data.limit_usd,
            period_type=data.period_type,
            policy=data.policy,
            warn_thresholds=list(data.warn_thresholds),
            effective_from=data.effective_from or utcnow().date(),
            is_active=True,
            created_by=actor.user_id,
        )
        repo.add(config)
        await session.flush()
        return before, config

    async def _usage_items(
        self,
        session: AsyncSession,
        scope: BudgetScope,
        configs: list[BudgetConfig],
        names: dict[uuid.UUID, str],
        period: str,
    ) -> list[BudgetUsageItem]:
        usages = await UsageReader(self._redis, session).read_many(
            scope, [config.scope_id for config in configs], period
        )
        items = [
            _build_item(config, names.get(config.scope_id), usages[config.scope_id])
            for config in configs
        ]
        return sorted(items, key=lambda item: item.usage_pct, reverse=True)

    async def _single_item(
        self,
        session: AsyncSession,
        scope: BudgetScope,
        scope_id: uuid.UUID,
        name: str | None,
        config: BudgetConfig | None,
        period: str,
    ) -> BudgetUsageItem:
        usage = await UsageReader(self._redis, session).read(scope, scope_id, period)
        if config is None:
            # 미설정 = 무제한. 한도 0 과 구분되도록 정책은 SOFT_WARN, 단계는 NORMAL 입니다.
            return BudgetUsageItem(
                scope=scope,
                scope_id=str(scope_id),
                name=name,
                limit_usd=ZERO,
                used_usd=usage.used_usd,
                remaining_usd=ZERO,
                usage_pct=Decimal("0.00"),
                policy=UNLIMITED_POLICY,
                alert_level=policy.AlertLevel.NORMAL,
                source=usage.source,
            )
        return _build_item(config, name, usage)

    async def _allocated_total(self, session: AsyncSession, team_id: uuid.UUID) -> Decimal:
        members = await UserRepository(session).list_by_team(team_id)
        configs = await BudgetConfigRepository(session).list_active(
            BudgetScope.USER, [member.id for member in members]
        )
        return policy.quantize_money(sum((config.limit_usd for config in configs), ZERO))

    async def _ensure_within_team_limit(
        self, session: AsyncSession, user: User, *, new_limit: Decimal
    ) -> None:
        """사용자 한도를 올려 팀 배분 합계가 팀 한도를 넘지 않는지 봅니다.

        하위가 상위를 우회할 수 없어야 한다는 규칙은 ADMIN 에게도 적용됩니다(00 문서).
        예외를 두면 "화면에는 합계 120, 한도 100"인 상태가 생깁니다.

        **호출 전에 `lock_team_budget` 이 잡혀 있어야 합니다.** 잠금 없이 부르면 두 요청이
        같은 합계를 읽고 각자 다른 사용자 행을 넣어 둘 다 통과합니다(write skew).
        """
        if user.team_id is None:
            return
        team_config = await BudgetConfigRepository(session).get_active(
            BudgetScope.TEAM, user.team_id
        )
        if team_config is None:
            return

        allocated = await self._allocated_total(session, user.team_id)
        current = await BudgetConfigRepository(session).get_active(BudgetScope.USER, user.id)
        projected = policy.quantize_money(
            allocated - (current.limit_usd if current else ZERO) + new_limit
        )
        if projected > team_config.limit_usd:
            raise ConflictError(
                "팀 예산 합계가 상위 예산을 초과합니다",
                code="budget_limit_conflict",
                details={
                    "team_id": str(user.team_id),
                    "allocated_usd": str(projected),
                    "limit_usd": str(team_config.limit_usd),
                },
            )

    @staticmethod
    def _ensure_can_manage_user_budget(actor: CurrentAdmin, user: User) -> None:
        """ADMIN 전체, 팀장은 자기 팀 멤버만. MEMBER 는 조회만 합니다(00 문서 인가 표)."""
        if actor.is_admin:
            return
        if actor.role != UserRole.TEAM_LEADER:
            raise ForbiddenError("예산을 설정할 권한이 없습니다")
        ensure_team_scope(actor, user.team_id)

    @staticmethod
    def _ensure_can_view_user_budget(actor: CurrentAdmin, user: User) -> None:
        """ADMIN / 팀장(자기 팀) / 본인. 소유권 검사는 router 가 아니라 여기서 끝냅니다.

        팀 소속을 봐야 판정되므로 의존성만으로는 끝나지 않습니다(00 문서: 소유권 검사가
        필요한 경우 service 가 다시 확인한다).
        """
        if actor.is_admin or actor.user_id == user.id:
            return
        if actor.role == UserRole.TEAM_LEADER:
            ensure_team_scope(actor, user.team_id)
            return
        raise ForbiddenError("본인 또는 상위 권한자만 조회할 수 있습니다")

    @staticmethod
    def _own_team(actor: CurrentAdmin) -> uuid.UUID:
        if actor.team_id is None:
            raise ForbiddenError("팀에 소속되지 않은 사용자는 조회할 수 없습니다")
        return actor.team_id

    async def _require_team(self, session: AsyncSession, team_id: uuid.UUID) -> Team:
        team = await TeamRepository(session).get(team_id)
        if team is None:
            raise NotFoundError("Team", str(team_id))
        return team

    async def _require_user(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        user = await UserRepository(session).get(user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return user

    async def _require_scope_target(
        self, session: AsyncSession, scope: BudgetScope, scope_id: uuid.UUID
    ) -> None:
        if scope == BudgetScope.TEAM:
            await self._require_team(session, scope_id)
        else:
            await self._require_user(session, scope_id)

    @staticmethod
    async def _team_names(session: AsyncSession, team_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await TeamRepository(session).names_for(team_ids)

    @staticmethod
    async def _user_names(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return await UserRepository(session).names_for(user_ids)

    async def _write_counters(
        self, items: list[tuple[BudgetScope, uuid.UUID, str, Decimal]]
    ) -> bool:
        """집행 카운터를 덮어씁니다. **재시드에서만** 호출합니다.

        전부 한 파이프라인(MULTI/EXEC)으로 보냅니다. 항목별로 나눠 쓰면 중간에 실패했을 때
        일부 카운터만 바뀐 상태가 남고, 그건 재시드가 고치려던 상태보다 나쁩니다.

        `INCRBYFLOAT` 가 읽을 수 있도록 지수 표기 없는 10진 문자열로 씁니다.
        """
        if not items:
            return True
        try:
            pipeline = self._redis.pipeline(transaction=True)
            for scope, scope_id, period, value in items:
                pipeline.set(
                    cache_keys.budget_usage_counter(scope.value, scope_id, period),
                    policy.counter_value(value),
                )
            await pipeline.execute()
            return True
        except Exception as exc:
            logger.error("budget.counter_write_failed", count=len(items), error=str(exc))
            return False

    async def _invalidate(self, keys: list[str]) -> None:
        if not keys:
            return
        result = await self._cache.invalidate(keys, context={"source": "budget_service"})
        if not result.ok:
            logger.warning("budget_service.cache_invalidation_incomplete", keys=result.failed_keys)


def _build_item(config: BudgetConfig, name: str | None, usage: ResolvedUsage) -> BudgetUsageItem:
    return BudgetUsageItem(
        scope=config.scope,
        scope_id=str(config.scope_id),
        name=name,
        limit_usd=config.limit_usd,
        used_usd=usage.used_usd,
        remaining_usd=policy.remaining(usage.used_usd, config.limit_usd),
        usage_pct=policy.usage_pct(usage.used_usd, config.limit_usd),
        policy=config.policy,
        alert_level=policy.alert_level(usage.used_usd, config.limit_usd, config.warn_thresholds),
        source=usage.source,
    )


def _combined_source(items: list[BudgetUsageItem]) -> str:
    """항목 출처의 종합.

    05 문서의 응답 예시는 최상위 `source` 하나지만, 항목마다 다를 수 있습니다. 한쪽으로
    뭉뚱그리면 거짓이 되므로 섞인 경우를 'mixed' 로 드러냅니다.
    """
    sources = {item.source for item in items}
    if not sources:
        return SOURCE_DB
    if len(sources) == 1:
        return sources.pop()
    return SOURCE_MIXED


def _to_breakdown(
    rows: list[UsageBreakdownRow], names: dict[uuid.UUID, str]
) -> list[UsageBreakdownItem]:
    return [
        UsageBreakdownItem(
            key=row.key,
            name=names.get(uuid.UUID(row.key)) if _is_uuid(row.key) else None,
            cost_usd=row.cost_usd,
            request_count=row.request_count,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
        )
        for row in rows
    ]


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
