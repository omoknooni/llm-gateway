"""budget 스키마 — SELECT + `budget_usages` UPSERT.

권한 범위는 공유 계약 C4 입니다. `budget_configs` 는 backend 가 소유하는 설정 원천이라
gateway 는 읽기만 하고, `budget_usages` 는 사용량 기록 경로가 누적하므로 UPSERT 가 허용됩니다
(backend 05 의 역할 분담표).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Integer

from gateway.schema.base import Base, BudgetPeriod, BudgetPolicy, BudgetScope, pg_enum


class BudgetConfig(Base):
    """활성 행은 `(scope, scope_id)` 당 하나입니다(partial unique index).

    설정을 고칠 때 backend 가 이전 행을 `is_active=false` 로 닫고 새 행을 만듭니다 —
    "언제 누가 한도를 올렸는가"가 감사에 남아야 하기 때문입니다. gateway 는 활성 행만 봅니다.
    """

    __tablename__ = "budget_configs"
    __table_args__ = {"schema": "budget"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    scope: Mapped[BudgetScope] = mapped_column(pg_enum(BudgetScope, "budget_scope", "budget"))
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    period_type: Mapped[BudgetPeriod] = mapped_column(pg_enum(BudgetPeriod, "budget_period", "budget"))
    policy: Mapped[BudgetPolicy] = mapped_column(pg_enum(BudgetPolicy, "budget_policy", "budget"))
    #: 임계 알림은 backend job 의 몫입니다. gateway 는 이 값을 집행에 쓰지 않습니다.
    warn_thresholds: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    is_active: Mapped[bool] = mapped_column(Boolean)


class BudgetUsage(Base):
    """월 소진의 내구 사본. PK 가 `(scope, scope_id, period)` 라 UPSERT 가 멱등합니다.

    Redis 카운터가 빠르고 이 테이블이 내구적입니다. 둘의 차이를 검증하는 것은 backend 의
    `verify_budget_counters` job 이고, **자동 교정하지 않습니다** — 두 주체가 같은 값을 쓰는
    경합을 만들기 때문입니다(backend 05).
    """

    __tablename__ = "budget_usages"
    __table_args__ = {"schema": "budget"}

    scope: Mapped[BudgetScope] = mapped_column(
        pg_enum(BudgetScope, "budget_scope", "budget"), primary_key=True
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    used_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    #: NOT NULL 이라 INSERT 경로에 값이 필요합니다. 집행이 본 한도를 그대로 넣습니다(docs/08).
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
