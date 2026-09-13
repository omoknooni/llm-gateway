"""예산 집행과 소진 누적.

집행은 **읽기만** 합니다(docs/08 의 4a). 누적은 응답을 반환한 뒤 `Finalize` 에서 일어납니다.

읽는 값이 두 종류라는 점이 이 서비스의 형태를 정합니다.

    설정  policy:budget:{scope}:{id}          미설정도 캐시합니다(음성 캐시)
    소진  budget:usage:{scope}:{id}:{period}  Redis 가 1차, budget_usages 가 2차

**소진은 "키 없음"과 "확인 불가"를 구분해야 합니다.** 키가 없는 것은 그 달의 첫 요청이라
0 이고, Redis 장애는 값을 모르는 것입니다. 둘을 같게 다루면 장애 중에 모든 팀의 소진이
0 으로 보여 예산이 통째로 열립니다. 그래서 여기서는 `cache.get_json` 의 "실패는 곧 miss"
규칙을 쓰지 않고 직접 예외를 봅니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.config import Settings
from gateway.core import cache, cache_keys
from gateway.core.clock import month_period, utcnow
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.policy.budget import BudgetState, BudgetVerdict, evaluate
from gateway.schema.base import BudgetScope
from gateway.schema.budget import BudgetConfig, BudgetUsage

logger = structlog.get_logger(__name__)

TEAM = "team"
USER = "user"

#: 소진액의 자릿수. `budget_usages.used_usd` 가 numeric(14,4) 입니다.
USED_PRECISION = Decimal("0.0001")


@dataclass(frozen=True)
class BudgetSetting:
    limit_usd: Decimal
    policy: str


@dataclass(frozen=True)
class BudgetOutcome:
    """집행 결과 + 누적 경로가 쓸 재료.

    한도는 `budget_usages.limit_usd`(NOT NULL) 의 INSERT 값이 됩니다. 집행이 본 값과
    스냅샷이 같아야 하므로 여기서 함께 들고 내려갑니다(docs/08).
    """

    verdict: BudgetVerdict
    period: str
    team_limit: Decimal
    user_limit: Decimal | None
    #: 의존성 장애로 집행하지 못했습니다. fail-open 이지만 조용하면 안 됩니다.
    degraded: bool = False


def format_amount(value: Decimal) -> str:
    """지수 표기 금지.

    `INCRBYFLOAT` 가 `1E+2` 를 파싱하지 못합니다. backend 05 가 재시드 경로에서 같은 제약을
    지키고 있어, 양쪽이 같은 규칙을 쓰지 않으면 한쪽이 쓴 값을 다른 쪽이 깨뜨립니다.
    """
    return format(value.quantize(USED_PRECISION), "f")


class BudgetService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ── 집행 (읽기 전용) ──

    async def evaluate(
        self,
        *,
        auth: AuthContext,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> BudgetOutcome:
        period = month_period()
        degraded = False
        states: list[BudgetState | None] = []
        limits: dict[str, Decimal | None] = {TEAM: Decimal("0"), USER: None}

        # 사용자 → 팀 순서입니다. 본인이 고칠 수 없는 이유로 막히는 것보다 자기 한도로
        # 막히는 편이 행동으로 옮기기 쉽습니다(policy/budget.evaluate).
        targets = [(USER, auth.user_id), (TEAM, auth.team_id)]
        for scope, scope_id in targets:
            if scope_id is None:
                # TEAM 소유 VK 입니다. 귀속될 사람이 없으므로 팀 예산만 봅니다.
                states.append(None)
                continue

            setting = await self._setting(scope, scope_id, redis, session_factory)
            if setting is None:
                if scope == USER:
                    limits[USER] = None
                continue
            limits[scope] = setting.limit_usd

            used = await self._used(scope, scope_id, period, redis, session_factory)
            if used is None:
                degraded = True
                logger.warning(
                    "budget.usage_unavailable_fail_open", scope=scope, scope_id=scope_id
                )
                continue

            states.append(
                BudgetState(
                    scope=scope.upper(),
                    scope_id=scope_id,
                    limit_usd=setting.limit_usd,
                    policy=setting.policy,
                    used_usd=used,
                )
            )

        verdict = evaluate(*states)
        for warned in verdict.warnings:
            logger.warning(
                "budget.soft_warn_exceeded",
                scope=warned.scope,
                scope_id=warned.scope_id,
                used=str(warned.used_usd),
                limit=str(warned.limit_usd),
            )

        return BudgetOutcome(
            verdict=verdict,
            period=period,
            team_limit=limits[TEAM] or Decimal("0"),
            user_limit=limits[USER],
            degraded=degraded,
        )

    def enforce(self, outcome: BudgetOutcome) -> None:
        """`HARD_BLOCK` 초과를 거절로 옮깁니다.

        `Retry-After` 를 붙이지 않습니다. 월 예산 초과는 최대 31일 뒤에야 풀리고, 그 값을
        그대로 주면 SDK 가 그만큼 잠듭니다. **기다려서 풀리는 상태가 아니라 사람이 한도를
        올려야 풀리는 상태**라 답이 존재하지 않는 쪽이 정직합니다(docs/08).
        """
        blocked = outcome.verdict.blocked_by
        if blocked is None:
            return
        logger.info(
            "budget.blocked",
            scope=blocked.scope,
            scope_id=blocked.scope_id,
            used=str(blocked.used_usd),
            limit=str(blocked.limit_usd),
        )
        raise GatewayError(
            ErrorCode.BUDGET_EXCEEDED,
            f"{blocked.scope.capitalize()} budget for {outcome.period} is exhausted "
            f"({blocked.used_usd} / {blocked.limit_usd} USD)",
            outcome=AuthOutcome.BUDGET_EXCEEDED,
        )

    # ── 누적 (쓰기) ──

    async def accumulate(
        self,
        *,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
        auth: AuthContext,
        outcome: BudgetOutcome,
        cost: Decimal,
    ) -> None:
        """Redis 카운터와 `budget_usages` 를 함께 올립니다.

        비용이 0 이면 아무것도 하지 않습니다. 단가 미등록 모델이 카운터에 0 을 더하는 것은
        낭비이고 `budget_usages` 에 의미 없는 행을 만듭니다.
        """
        if cost <= 0:
            return

        targets = [(TEAM, auth.team_id, outcome.team_limit)]
        if auth.user_id is not None:
            targets.append((USER, auth.user_id, outcome.user_limit or Decimal("0")))

        for scope, scope_id, limit in targets:
            await self._incr_counter(redis, scope, scope_id, outcome.period, cost)
            await self._upsert_usage(session_factory, scope, scope_id, outcome.period, cost, limit)

    async def _incr_counter(
        self, redis, scope: str, scope_id: str, period: str, cost: Decimal
    ) -> None:
        if redis is None:
            return
        key = cache_keys.budget_usage_counter(scope, scope_id, period)
        try:
            await redis.incrbyfloat(key, float(format_amount(cost)))
            # NX 라 진행 중인 달의 만료를 계속 밀어내지 않습니다. 키에 기간이 들어 있어
            # 만료된 지난 달 키는 되살아나지 않습니다.
            await redis.expire(key, self._settings.budget_counter_ttl_seconds, nx=True)
        except Exception as exc:
            # 내구 사본은 budget_usages 입니다. 카운터만 놓치면 다음 집행이 DB 값을 봅니다.
            logger.warning("budget.counter_incr_failed", key=key, error=str(exc))

    async def _upsert_usage(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None,
        scope: str,
        scope_id: str,
        period: str,
        cost: Decimal,
        limit: Decimal,
    ) -> None:
        if session_factory is None:
            return
        try:
            async with session_factory() as db:
                await db.execute(
                    insert(BudgetUsage)
                    .values(
                        scope=scope.upper(),
                        scope_id=uuid.UUID(scope_id),
                        period=period,
                        used_usd=cost,
                        limit_usd=limit,
                        updated_at=utcnow(),
                    )
                    .on_conflict_do_update(
                        index_elements=["scope", "scope_id", "period"],
                        # limit_usd 는 갱신하지 않습니다 — 기간 시작 시점 스냅샷입니다.
                        set_={
                            "used_usd": BudgetUsage.__table__.c.used_usd + cost,
                            "updated_at": utcnow(),
                        },
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.warning("budget.usage_upsert_failed", scope=scope, error=str(exc))

    # ── 조회 ──

    async def _setting(
        self,
        scope: str,
        scope_id: str,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> BudgetSetting | None:
        key = cache_keys.budget_policy(scope, scope_id)
        cached = await cache.get_json(redis, key)
        if cached is not None:
            if not cached.get("set"):
                return None
            try:
                return BudgetSetting(
                    limit_usd=Decimal(cached["limit_usd"]), policy=cached["policy"]
                )
            except (KeyError, InvalidOperation):
                logger.warning("budget.cache_shape_invalid", key=key)

        if session_factory is None:
            return None

        try:
            async with session_factory() as db:
                row = (
                    await db.execute(
                        select(BudgetConfig).where(
                            BudgetConfig.scope == scope.upper(),
                            BudgetConfig.scope_id == uuid.UUID(scope_id),
                            BudgetConfig.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
        except Exception as exc:
            logger.warning("budget.config_lookup_failed", scope=scope, error=str(exc))
            return None

        setting = (
            BudgetSetting(limit_usd=row.limit_usd, policy=str(row.policy)) if row else None
        )
        # **미설정도 캐시합니다.** 예산이 없는 팀이 다수인 초기 운영에서 음성 캐시가 없으면
        # 거의 모든 요청이 DB 를 봅니다.
        payload = (
            {"set": True, "limit_usd": format_amount(setting.limit_usd), "policy": setting.policy}
            if setting
            else {"set": False}
        )
        await cache.set_json(redis, key, payload, self._settings.policy_cache_ttl_seconds)
        return setting

    async def _used(
        self,
        scope: str,
        scope_id: str,
        period: str,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> Decimal | None:
        """소진액. `None` 은 **확인 불가**이고 0 과 다릅니다."""
        if redis is not None:
            key = cache_keys.budget_usage_counter(scope, scope_id, period)
            try:
                raw = await redis.get(key)
            except Exception as exc:
                logger.warning("budget.counter_read_failed", key=key, error=str(exc))
            else:
                if raw is None:
                    return Decimal("0")  # 그 달의 첫 요청입니다.
                try:
                    return Decimal(raw if isinstance(raw, str) else raw.decode())
                except (InvalidOperation, AttributeError):
                    logger.warning("budget.counter_value_invalid", key=key)

        if session_factory is None:
            return None
        try:
            async with session_factory() as db:
                used = (
                    await db.execute(
                        select(BudgetUsage.used_usd).where(
                            BudgetUsage.scope == BudgetScope(scope.upper()),
                            BudgetUsage.scope_id == uuid.UUID(scope_id),
                            BudgetUsage.period == period,
                        )
                    )
                ).scalar_one_or_none()
        except Exception as exc:
            logger.warning("budget.usage_lookup_failed", scope=scope, error=str(exc))
            return None
        return used if used is not None else Decimal("0")
