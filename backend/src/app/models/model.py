"""model 스키마 — 모델 alias, 단가, 허용 모델, rate limit 설정.

gateway 는 이 스키마를 SELECT 만 합니다(08 문서 C4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import (
    ApiDialect,
    ModelStatus,
    Provider,
    RateLimitScope,
    pg_enum,
)
from app.models.mixins import TimestampMixin

#: rate limit 유일성 인덱스에서 NULL scope_id 를 대표하는 값.
NULL_SCOPE_SENTINEL = "00000000-0000-0000-0000-000000000000"


class ModelAlias(Base, TimestampMixin):
    """client 가 `model` 필드에 넣는 값이 PK 입니다.

    요청 경로의 조회 키이자 캐시 키(`policy:model:{alias}`)이므로 변경할 수 없습니다.
    이름을 바꾸려면 새 alias 를 만들고 구 alias 를 INACTIVE 로 내립니다(04 문서).
    """

    __tablename__ = "model_aliases"
    __table_args__ = (
        CheckConstraint("alias ~ '^[a-z0-9][a-z0-9.-]{1,127}$'", name="ck_model_alias_format"),
        CheckConstraint("array_length(supported_dialects, 1) >= 1", name="ck_model_dialects_not_empty"),
        {"schema": "model"},
    )

    alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[Provider] = mapped_column(pg_enum(Provider, "provider", "model"), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(512), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: ADR-0003. 모델마다 노출 방언이 다를 수 있습니다.
    supported_dialects: Mapped[list[ApiDialect]] = mapped_column(
        ARRAY(pg_enum(ApiDialect, "api_dialect", "model")), nullable=False
    )
    status: Mapped[ModelStatus] = mapped_column(
        pg_enum(ModelStatus, "model_status", "model"), nullable=False, default=ModelStatus.ACTIVE
    )
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_streaming: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)

    pricings: Mapped[list[ModelPricing]] = relationship(back_populates="model", lazy="raise")


class ModelPricing(Base):
    """단가 시계열. 행은 수정하지 않고, 새 행을 넣고 이전 구간을 닫습니다.

    같은 alias 의 유효 구간은 겹칠 수 없습니다. 애플리케이션 검증만으로는 동시 요청에서
    겹치므로 DB 의 EXCLUDE 제약으로 막습니다(마이그레이션 0001).
    """

    __tablename__ = "model_pricings"
    __table_args__ = (
        CheckConstraint(
            "input_price_per_1k >= 0 AND output_price_per_1k >= 0", name="ck_pricing_non_negative"
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from", name="ck_pricing_period_order"
        ),
        Index("ix_model_pricings_alias_from", "model_alias", "effective_from"),
        {"schema": "model"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_alias: Mapped[str] = mapped_column(
        String(128), ForeignKey("model.model_aliases.alias"), nullable=False
    )
    input_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    output_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    cache_write_price_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(14, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    cache_read_price_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(14, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model: Mapped[ModelAlias] = relationship(back_populates="pricings", lazy="raise")


class TeamAllowedModel(Base):
    """팀 허용 모델. 행이 0개면 카탈로그의 ACTIVE 전체 허용입니다."""

    __tablename__ = "team_allowed_models"
    __table_args__ = {"schema": "model"}

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth.teams.id", ondelete="CASCADE"), primary_key=True
    )
    model_alias: Mapped[str] = mapped_column(
        String(128), ForeignKey("model.model_aliases.alias"), primary_key=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserAllowedModel(Base):
    """사용자 override. 행이 있으면 팀 정책을 덮어쓰고, 0개면 팀 정책으로 폴백합니다.

    0개가 '전체 허용'이 아니라는 점이 팀 층과 다릅니다(04 문서).
    """

    __tablename__ = "user_allowed_models"
    __table_args__ = {"schema": "model"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True
    )
    model_alias: Mapped[str] = mapped_column(
        String(128), ForeignKey("model.model_aliases.alias"), primary_key=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RateLimitConfig(Base, TimestampMixin):
    """rate limit 설정. 집행과 카운팅은 gateway 가 합니다(06 문서)."""

    __tablename__ = "rate_limit_configs"
    __table_args__ = (
        CheckConstraint(
            "rpm_limit IS NOT NULL OR tpm_limit IS NOT NULL OR concurrency_limit IS NOT NULL",
            name="ck_rate_limit_not_empty",
        ),
        CheckConstraint(
            "(rpm_limit IS NULL OR rpm_limit > 0) "
            "AND (tpm_limit IS NULL OR tpm_limit > 0) "
            "AND (concurrency_limit IS NULL OR concurrency_limit > 0)",
            name="ck_rate_limit_positive",
        ),
        CheckConstraint(
            "(scope = 'GLOBAL' AND scope_id IS NULL) OR (scope <> 'GLOBAL' AND scope_id IS NOT NULL)",
            name="ck_rate_limit_scope_id",
        ),
        Index(
            "uq_rate_limit_active",
            "scope",
            text(f"COALESCE(scope_id, '{NULL_SCOPE_SENTINEL}'::uuid)"),
            text("COALESCE(model_alias, '*')"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {"schema": "model"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope: Mapped[RateLimitScope] = mapped_column(
        pg_enum(RateLimitScope, "rate_limit_scope", "model"), nullable=False
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    #: NULL 이면 그 scope 의 모든 모델에 적용됩니다.
    model_alias: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("model.model_aliases.alias"), nullable=True
    )
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrency_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
