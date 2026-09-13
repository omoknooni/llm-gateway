from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RateLimitScope
from app.models.model import RateLimitConfig


class RateLimitRepository:
    """rate limit 설정. backend 가 소유하고 gateway 는 읽기만 합니다(06 문서).

    설정 변경은 예산과 달리 **이전 행을 닫고 새 행을 만들지 않습니다.** 한도는 "언제 누가
    올렸는가"보다 현재 값이 중요하고, 변경 이력은 감사 로그가 답합니다. 대신 부분 unique
    index `uq_rate_limit_active` 가 활성 행을 조합당 하나로 강제합니다.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self,
        scope: RateLimitScope,
        scope_id: uuid.UUID | None,
        model_alias: str | None,
        *,
        for_update: bool = False,
    ) -> RateLimitConfig | None:
        stmt = select(RateLimitConfig).where(
            RateLimitConfig.scope == scope,
            RateLimitConfig.is_active.is_(True),
            RateLimitConfig.scope_id.is_(None)
            if scope_id is None
            else RateLimitConfig.scope_id == scope_id,
            RateLimitConfig.model_alias.is_(None)
            if model_alias is None
            else RateLimitConfig.model_alias == model_alias,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_subject(
        self,
        *,
        team_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        virtual_key_id: uuid.UUID | None,
        model_alias: str | None,
    ) -> list[RateLimitConfig]:
        """해석에 필요한 행을 **한 번에** 가져옵니다.

        층마다 따로 조회하면 그 사이에 설정이 바뀌어 해석 결과가 섞일 수 있고, 왕복도
        여섯 번이 됩니다.

        `model_alias` 를 지정하면 그 모델 행과 전체(NULL) 행을 함께 가져옵니다 — 폴백이
        한도 종류별로 일어나므로 둘 다 후보입니다.
        """
        subject_filters = []
        if virtual_key_id is not None:
            subject_filters.append(
                (RateLimitConfig.scope == RateLimitScope.VIRTUAL_KEY)
                & (RateLimitConfig.scope_id == virtual_key_id)
            )
        if user_id is not None:
            subject_filters.append(
                (RateLimitConfig.scope == RateLimitScope.USER)
                & (RateLimitConfig.scope_id == user_id)
            )
        if team_id is not None:
            subject_filters.append(
                (RateLimitConfig.scope == RateLimitScope.TEAM)
                & (RateLimitConfig.scope_id == team_id)
            )
        # GLOBAL 은 주체가 무엇이든 항상 후보입니다(별도 축).
        subject_filters.append(RateLimitConfig.scope == RateLimitScope.GLOBAL)

        stmt = select(RateLimitConfig).where(RateLimitConfig.is_active.is_(True))
        combined = subject_filters[0]
        for extra in subject_filters[1:]:
            combined = combined | extra
        stmt = stmt.where(combined)

        if model_alias is not None:
            stmt = stmt.where(
                RateLimitConfig.model_alias.is_(None)
                | (RateLimitConfig.model_alias == model_alias)
            )
        else:
            # 모델을 지정하지 않은 조회는 "모든 모델" 설정만 봅니다.
            stmt = stmt.where(RateLimitConfig.model_alias.is_(None))

        return list((await self._session.execute(stmt)).scalars().all())

    async def list_configs(
        self,
        *,
        scope: RateLimitScope | None = None,
        scope_id: uuid.UUID | None = None,
        model_alias: str | None = None,
        scope_ids: list[uuid.UUID] | None = None,
    ) -> list[RateLimitConfig]:
        stmt = select(RateLimitConfig).where(RateLimitConfig.is_active.is_(True))
        if scope is not None:
            stmt = stmt.where(RateLimitConfig.scope == scope)
        if scope_id is not None:
            stmt = stmt.where(RateLimitConfig.scope_id == scope_id)
        if scope_ids is not None:
            if not scope_ids:
                return []
            stmt = stmt.where(RateLimitConfig.scope_id.in_(scope_ids))
        if model_alias is not None:
            stmt = stmt.where(RateLimitConfig.model_alias == model_alias)
        return list(
            (
                await self._session.execute(
                    stmt.order_by(RateLimitConfig.scope, RateLimitConfig.model_alias)
                )
            )
            .scalars()
            .all()
        )

    def add(self, config: RateLimitConfig) -> None:
        self._session.add(config)
