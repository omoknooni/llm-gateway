from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ModelStatus
from app.models.model import (
    ModelAlias,
    ModelPricing,
    TeamAllowedModel,
    UserAllowedModel,
)


class ModelAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, alias: str, *, for_update: bool = False) -> ModelAlias | None:
        stmt = select(ModelAlias).where(ModelAlias.alias == alias)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_aliases(self, *, status: ModelStatus | None = None) -> list[ModelAlias]:
        stmt = select(ModelAlias).order_by(ModelAlias.alias)
        if status is not None:
            stmt = stmt.where(ModelAlias.status == status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_active_aliases(self) -> list[str]:
        stmt = select(ModelAlias.alias).where(ModelAlias.status == ModelStatus.ACTIVE)
        return list((await self._session.execute(stmt)).scalars().all())

    async def exists_all(self, aliases: list[str]) -> set[str]:
        """존재하는 alias 집합을 돌려줍니다. 호출자가 차집합으로 없는 것을 찾습니다."""
        if not aliases:
            return set()
        stmt = select(ModelAlias.alias).where(ModelAlias.alias.in_(aliases))
        return set((await self._session.execute(stmt)).scalars().all())

    def add(self, alias: ModelAlias) -> None:
        self._session.add(alias)


class ModelPricingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_alias(self, alias: str) -> list[ModelPricing]:
        stmt = (
            select(ModelPricing)
            .where(ModelPricing.model_alias == alias)
            .order_by(ModelPricing.effective_from.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def current_for_alias(self, alias: str, *, at: datetime) -> ModelPricing | None:
        stmt = (
            select(ModelPricing)
            .where(
                ModelPricing.model_alias == alias,
                ModelPricing.effective_from <= at,
                (ModelPricing.effective_until.is_(None)) | (ModelPricing.effective_until > at),
            )
            .order_by(ModelPricing.effective_from.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def open_ended_for_alias(self, alias: str) -> ModelPricing | None:
        """아직 닫히지 않은 구간. 새 단가를 넣을 때 이 구간을 닫습니다."""
        stmt = (
            select(ModelPricing)
            .where(ModelPricing.model_alias == alias, ModelPricing.effective_until.is_(None))
            .order_by(ModelPricing.effective_from.desc())
            .limit(1)
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def aliases_without_current_pricing(self, *, at: datetime) -> list[str]:
        active = select(ModelAlias.alias).where(ModelAlias.status == ModelStatus.ACTIVE)
        priced = select(ModelPricing.model_alias).where(
            ModelPricing.effective_from <= at,
            (ModelPricing.effective_until.is_(None)) | (ModelPricing.effective_until > at),
        )
        stmt = active.where(ModelAlias.alias.not_in(priced))
        return list((await self._session.execute(stmt)).scalars().all())

    def add(self, pricing: ModelPricing) -> None:
        self._session.add(pricing)


class AllowedModelRepository:
    """팀/사용자 허용 모델. 두 테이블의 구조가 같아 한 클래스로 다룹니다."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_team(self, team_id: uuid.UUID) -> list[str]:
        stmt = select(TeamAllowedModel.model_alias).where(TeamAllowedModel.team_id == team_id)
        return sorted((await self._session.execute(stmt)).scalars().all())

    async def list_for_user(self, user_id: uuid.UUID) -> list[str]:
        stmt = select(UserAllowedModel.model_alias).where(UserAllowedModel.user_id == user_id)
        return sorted((await self._session.execute(stmt)).scalars().all())

    async def replace_for_team(
        self, team_id: uuid.UUID, aliases: list[str], *, actor_id: uuid.UUID
    ) -> None:
        """전체 교체. 부분 추가/삭제 API 를 두지 않는 이유는 04 문서에 있습니다."""
        await self._session.execute(
            delete(TeamAllowedModel).where(TeamAllowedModel.team_id == team_id)
        )
        self._session.add_all(
            [
                TeamAllowedModel(team_id=team_id, model_alias=alias, created_by=actor_id)
                for alias in aliases
            ]
        )

    async def replace_for_user(
        self, user_id: uuid.UUID, aliases: list[str], *, actor_id: uuid.UUID
    ) -> None:
        await self._session.execute(
            delete(UserAllowedModel).where(UserAllowedModel.user_id == user_id)
        )
        self._session.add_all(
            [
                UserAllowedModel(user_id=user_id, model_alias=alias, created_by=actor_id)
                for alias in aliases
            ]
        )
