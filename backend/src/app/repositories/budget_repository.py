from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Team, User
from app.models.budget import BudgetConfig, BudgetUsage
from app.models.enums import BudgetScope


class BudgetConfigRepository:
    """예산 설정. backend 가 소유하는 유일한 예산 테이블입니다.

    설정 변경은 UPDATE 가 아니라 **이전 행을 닫고 새 행을 추가**합니다(05 문서). 부분 unique
    index `uq_budget_config_active` 가 활성 행을 scope 당 하나로 강제하므로, 새 행을 넣기 전에
    이전 행을 닫고 flush 해야 합니다.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self, scope: BudgetScope, scope_id: uuid.UUID, *, for_update: bool = False
    ) -> BudgetConfig | None:
        stmt = select(BudgetConfig).where(
            BudgetConfig.scope == scope,
            BudgetConfig.scope_id == scope_id,
            BudgetConfig.is_active.is_(True),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active(
        self, scope: BudgetScope, scope_ids: list[uuid.UUID] | None = None
    ) -> list[BudgetConfig]:
        stmt = select(BudgetConfig).where(
            BudgetConfig.scope == scope, BudgetConfig.is_active.is_(True)
        )
        if scope_ids is not None:
            if not scope_ids:
                return []
            stmt = stmt.where(BudgetConfig.scope_id.in_(scope_ids))
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all_active(self) -> list[BudgetConfig]:
        """job 이 도는 전체 활성 설정. scope 를 섞어 돌려줍니다."""
        stmt = select(BudgetConfig).where(BudgetConfig.is_active.is_(True))
        return list((await self._session.execute(stmt)).scalars().all())

    async def teams_without_budget(self) -> list[Team]:
        """활성 팀 중 예산 미설정.

        미설정은 **무제한**으로 해석하므로(05 문서), 이 목록이 운영 화면에 상시 노출되지 않으면
        설정을 빠뜨린 사고와 의도적 무제한을 구분할 수 없습니다.
        """
        having_budget = select(BudgetConfig.scope_id).where(
            BudgetConfig.scope == BudgetScope.TEAM, BudgetConfig.is_active.is_(True)
        )
        stmt = (
            select(Team)
            .where(Team.is_active.is_(True), Team.id.not_in(having_budget))
            .order_by(Team.name)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def users_without_budget(self, *, team_id: uuid.UUID | None = None) -> list[User]:
        having_budget = select(BudgetConfig.scope_id).where(
            BudgetConfig.scope == BudgetScope.USER, BudgetConfig.is_active.is_(True)
        )
        stmt = (
            select(User)
            .where(User.is_active.is_(True), User.id.not_in(having_budget))
            .order_by(User.display_name)
        )
        if team_id is not None:
            stmt = stmt.where(User.team_id == team_id)
        return list((await self._session.execute(stmt)).scalars().all())

    def add(self, config: BudgetConfig) -> None:
        self._session.add(config)


class BudgetUsageRepository:
    """기간별 소진 내구 사본.

    **쓰기 주체는 data plane 입니다.** backend 는 조회하고, 두 가지 예외로만 씁니다 —
    임계 도달 기록(`notified_thresholds`)과 ADMIN 재시드(05 문서).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, scope: BudgetScope, scope_id: uuid.UUID, period: str, *, for_update: bool = False
    ) -> BudgetUsage | None:
        stmt = select(BudgetUsage).where(
            BudgetUsage.scope == scope,
            BudgetUsage.scope_id == scope_id,
            BudgetUsage.period == period,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def map_for(
        self, scope: BudgetScope, scope_ids: list[uuid.UUID], period: str
    ) -> dict[uuid.UUID, BudgetUsage]:
        """scope_id → 소진 행. 목록 조회에서 N+1 을 피하기 위한 형태입니다."""
        if not scope_ids:
            return {}
        stmt = select(BudgetUsage).where(
            BudgetUsage.scope == scope,
            BudgetUsage.scope_id.in_(scope_ids),
            BudgetUsage.period == period,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {row.scope_id: row for row in rows}

    def add(
        self,
        *,
        scope: BudgetScope,
        scope_id: uuid.UUID,
        period: str,
        used_usd: Decimal,
        limit_usd: Decimal,
    ) -> BudgetUsage:
        row = BudgetUsage(
            scope=scope, scope_id=scope_id, period=period, used_usd=used_usd, limit_usd=limit_usd
        )
        self._session.add(row)
        return row
