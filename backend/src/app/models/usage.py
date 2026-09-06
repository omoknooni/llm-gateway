"""usage 스키마 — 사용량 원천 이벤트와 집계.

`usage_events` 는 **gateway 가 INSERT** 하고 backend 는 읽기만 합니다. 스키마는 backend 가
정의하지만 내용은 gateway 가 결정합니다(08 문서 C5). 집계 테이블은 backend 의 job 이 씁니다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ApiDialect, UsageStatus, pg_enum


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_occurred_at", "occurred_at"),
        Index("ix_usage_events_team_occurred", "team_id", "occurred_at"),
        Index("ix_usage_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_usage_events_vk_occurred", "virtual_key_id", "occurred_at"),
        Index("ix_usage_events_model_occurred", "model_alias", "occurred_at"),
        {"schema": "usage"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    #: 재시도 시 중복 INSERT 방지.
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.teams.id"), nullable=False)
    #: TEAM 소유 VK 호출은 사람에 귀속되지 않으므로 NULL 입니다.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=True)
    virtual_key_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth.virtual_keys.id"), nullable=False
    )
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(512), nullable=False)
    #: 집계는 방언 중립이지만 방언별 분해도 가능해야 합니다.
    dialect: Mapped[ApiDialect] = mapped_column(pg_enum(ApiDialect, "api_dialect", "model"), nullable=False)
    status: Mapped[UsageStatus] = mapped_column(
        pg_enum(UsageStatus, "usage_status", "usage"), nullable=False
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: provider 응답에 usage 가 없어 추정한 경우 true.
    estimated_usage: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, server_default="0"
    )
    #: 어떤 단가로 계산했는지 추적. 단가 소급 변경 시 재계산 대상을 찾는 근거입니다.
    pricing_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("model.model_pricings.id"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class _AggregateColumns:
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), nullable=False, server_default="0"
    )
    avg_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    p95_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    aggregated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyUsageAggregate(Base, _AggregateColumns):
    """대시보드와 리더보드는 원천이 아니라 이 테이블을 읽습니다."""

    __tablename__ = "daily_usage_aggregates"
    __table_args__ = {"schema": "usage"}

    bucket_date: Mapped[date] = mapped_column(Date, primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    virtual_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)


class MonthlyUsageAggregate(Base, _AggregateColumns):
    __tablename__ = "monthly_usage_aggregates"
    __table_args__ = {"schema": "usage"}

    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    virtual_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
