"""budget 스키마 — 예산 설정과 기간별 소진.

`budget_configs` 는 backend 가 소유합니다. `budget_usages` 의 쓰기 주체는 data plane 이고,
backend 는 조회하거나 관리자 재시드로만 씁니다(05 문서).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import BudgetPeriod, BudgetPolicy, BudgetScope, pg_enum
from app.models.mixins import TimestampMixin


class BudgetConfig(Base, TimestampMixin):
    __tablename__ = "budget_configs"
    __table_args__ = (
        CheckConstraint("limit_usd >= 0", name="ck_budget_limit_non_negative"),
        Index(
            "uq_budget_config_active",
            "scope",
            "scope_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {"schema": "budget"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope: Mapped[BudgetScope] = mapped_column(pg_enum(BudgetScope, "budget_scope", "budget"), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    period_type: Mapped[BudgetPeriod] = mapped_column(
        pg_enum(BudgetPeriod, "budget_period", "budget"), nullable=False, default=BudgetPeriod.MONTHLY
    )
    policy: Mapped[BudgetPolicy] = mapped_column(
        pg_enum(BudgetPolicy, "budget_policy", "budget"), nullable=False, default=BudgetPolicy.HARD_BLOCK
    )
    #: 경고 발송 기준(%). 중복 발송 방지는 budget_usages.notified_thresholds 가 합니다.
    warn_thresholds: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{80,90,100}"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)


class BudgetUsage(Base):
    """기간별 소진 내구 사본. Redis 카운터가 빠른 사본이고 이 테이블이 내구 사본입니다.

    쓰기 주체는 data plane 입니다(gateway 또는 사용량 기록 경로).
    """

    __tablename__ = "budget_usages"
    __table_args__ = (
        CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_budget_usage_period_format"),
        {"schema": "budget"},
    )

    scope: Mapped[BudgetScope] = mapped_column(
        pg_enum(BudgetScope, "budget_scope", "budget"), primary_key=True
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    #: UTC 기준 월. "YYYY-MM"
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    used_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    #: 기간 시작 시점 한도 스냅샷. 집행은 현재 설정을 따릅니다.
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    notified_thresholds: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
