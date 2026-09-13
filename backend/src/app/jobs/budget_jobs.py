"""예산 점검 작업.

두 작업 모두 **고치지 않고 알립니다.**

- `check_budget_thresholds` — 임계 도달을 감지해 `notified_thresholds` 에 기록합니다.
  실제 발송 채널 연동은 Phase 4 입니다(05 문서 미결정).
- `verify_budget_counters` — Redis 카운터와 DB 내구 사본의 차이를 봅니다. **자동 교정하지
  않습니다.** 교정하면 gateway 와 backend 두 주체가 같은 값을 동시에 쓰는 경합이 생깁니다.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.clock import month_period
from app.core.config import get_settings
from app.models.budget import BudgetConfig
from app.models.enums import BudgetScope
from app.policy import budget as policy
from app.repositories.budget_repository import BudgetConfigRepository, BudgetUsageRepository
from app.services.budget_service import UsageReader

logger = structlog.get_logger()


def _by_scope(configs: list[BudgetConfig]) -> dict[BudgetScope, list[BudgetConfig]]:
    grouped: dict[BudgetScope, list[BudgetConfig]] = defaultdict(list)
    for config in configs:
        grouped[config.scope].append(config)
    return grouped


async def check_budget_thresholds(session: AsyncSession, redis: aioredis.Redis) -> int:
    """임계 도달 감지. 새로 넘은 임계 수를 돌려줍니다.

    `budget_usages` 행이 없으면 건너뜁니다. 행을 만드는 주체는 data plane 이고, 여기서
    만들면 소진 기록의 쓰기 주체가 둘이 됩니다(05 문서). 행이 없다는 것은 이번 달 사용이
    아직 기록되지 않았다는 뜻이므로 알릴 임계도 없습니다.
    """
    period = month_period()
    configs = await BudgetConfigRepository(session).list_all_active()
    reader = UsageReader(redis, session)
    usage_repo = BudgetUsageRepository(session)

    newly_crossed = 0
    for scope, scope_configs in _by_scope(configs).items():
        scope_ids = [config.scope_id for config in scope_configs]
        usages = await reader.read_many(scope, scope_ids, period)
        rows = await usage_repo.map_for(scope, scope_ids, period)

        for config in scope_configs:
            used = usages[config.scope_id].used_usd
            crossed = policy.crossed_thresholds(used, config.limit_usd, config.warn_thresholds)
            if not crossed:
                continue

            row = rows.get(config.scope_id)
            if row is None:
                logger.info(
                    "budget.threshold_reached_without_usage_row",
                    scope=scope.value,
                    scope_id=str(config.scope_id),
                    period=period,
                )
                continue

            already = set(row.notified_thresholds)
            fresh = [t for t in crossed if t not in already]
            if not fresh:
                continue

            row.notified_thresholds = sorted(already | set(crossed))
            newly_crossed += len(fresh)
            logger.warning(
                "budget.threshold_crossed",
                scope=scope.value,
                scope_id=str(config.scope_id),
                period=period,
                thresholds=fresh,
                used_usd=str(used),
                limit_usd=str(config.limit_usd),
                alert_level=policy.alert_level(
                    used, config.limit_usd, config.warn_thresholds
                ).value,
            )
            await audit.record_system(
                session,
                action="BUDGET_THRESHOLD_CROSSED",
                resource_type="budget_usage",
                resource_id=f"{scope.value}:{config.scope_id}:{period}",
                changes={
                    "thresholds": fresh,
                    "used_usd": str(used),
                    "limit_usd": str(config.limit_usd),
                },
            )

    await session.commit()
    return newly_crossed


async def verify_budget_counters(session: AsyncSession, redis: aioredis.Redis) -> int:
    """Redis 카운터와 DB 내구 사본의 차이 검증. 경고만 하고 **교정하지 않습니다.**

    차이가 나는 정상 상황이 있습니다 — 월 경계 직후 카운터가 없는 것, data plane 이 아직
    DB 에 UPSERT 하지 않은 지연분. 그래서 임계(`BUDGET_COUNTER_DRIFT_WARN_USD`)를 두고
    그보다 큰 차이만 봅니다.
    """
    period = month_period()
    tolerance = Decimal(str(get_settings().BUDGET_COUNTER_DRIFT_WARN_USD))
    configs = await BudgetConfigRepository(session).list_all_active()
    reader = UsageReader(redis, session)
    usage_repo = BudgetUsageRepository(session)

    mismatches = 0
    for scope, scope_configs in _by_scope(configs).items():
        scope_ids = [config.scope_id for config in scope_configs]
        counters = await reader.read_counters(scope, scope_ids, period)
        rows = await usage_repo.map_for(scope, scope_ids, period)

        for scope_id in scope_ids:
            counter = counters.get(scope_id)
            if counter is None:
                # 카운터가 아직 없는 것은 정상입니다(월 경계 직후 0 에서 시작).
                continue
            durable = rows[scope_id].used_usd if scope_id in rows else Decimal("0")
            drift = abs(counter - durable)
            if drift > tolerance:
                mismatches += 1
                logger.warning(
                    "budget.counter_drift",
                    scope=scope.value,
                    scope_id=str(scope_id),
                    period=period,
                    redis_usd=str(counter),
                    db_usd=str(durable),
                    drift_usd=str(drift),
                )

    if mismatches:
        logger.warning("job.budget_counter_drift_total", count=mismatches, period=period)
    return mismatches
