"""사용량 집계 조회.

원천(`usage.usage_events`)이 아니라 **월 집계 테이블**을 읽습니다. 예산 화면이 원천을 스캔하면
이벤트가 쌓일수록 조회가 느려지고, 같은 숫자를 대시보드와 다르게 계산하게 됩니다.

집계 테이블을 채우는 job 은 M7 소유입니다. M6 는 읽기만 하므로, 집계가 비어 있으면
breakdown 이 빈 목록으로 나옵니다(총 소진액은 `budget_usages` / Redis 카운터에서 옵니다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import MonthlyUsageAggregate


@dataclass(frozen=True)
class UsageBreakdownRow:
    key: str
    cost_usd: Decimal
    request_count: int
    input_tokens: int
    output_tokens: int


_COST = func.coalesce(func.sum(MonthlyUsageAggregate.estimated_cost_usd), 0)
_REQUESTS = func.coalesce(func.sum(MonthlyUsageAggregate.request_count), 0)
_INPUT = func.coalesce(func.sum(MonthlyUsageAggregate.input_tokens), 0)
_OUTPUT = func.coalesce(func.sum(MonthlyUsageAggregate.output_tokens), 0)


def _to_rows(result) -> list[UsageBreakdownRow]:
    return [
        UsageBreakdownRow(
            key=str(key),
            cost_usd=Decimal(cost),
            request_count=int(requests),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
        )
        for key, cost, requests, input_tokens, output_tokens in result
    ]


class UsageAggregateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def team_breakdown_by_user(self, team_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.user_id, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.team_id == team_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.user_id)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))

    async def team_breakdown_by_model(self, team_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.model_alias, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.team_id == team_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.model_alias)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))

    async def user_breakdown_by_model(self, user_id: uuid.UUID, period: str) -> list[UsageBreakdownRow]:
        stmt = (
            select(MonthlyUsageAggregate.model_alias, _COST, _REQUESTS, _INPUT, _OUTPUT)
            .where(
                MonthlyUsageAggregate.user_id == user_id,
                MonthlyUsageAggregate.period == period,
            )
            .group_by(MonthlyUsageAggregate.model_alias)
            .order_by(_COST.desc())
        )
        return _to_rows(await self._session.execute(stmt))
