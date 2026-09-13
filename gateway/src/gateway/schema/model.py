"""model 스키마 — SELECT 전용."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from gateway.schema.base import (
    ApiDialect,
    Base,
    ModelStatus,
    Provider,
    RateLimitScope,
    pg_enum,
)


class ModelAlias(Base):
    """`alias` 가 PK 입니다 — 요청 경로의 조회 키이자 캐시 키(`policy:model:{alias}`)."""

    __tablename__ = "model_aliases"
    __table_args__ = {"schema": "model"}

    alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[Provider] = mapped_column(pg_enum(Provider, "provider", "model"))
    provider_model_id: Mapped[str] = mapped_column(String(512))
    #: NULL 이면 배포 기본 리전. 리전 접두사 재작성의 입력입니다(docs/04).
    region: Mapped[str | None] = mapped_column(String(64))
    #: S2. Mantle 계열만 사용합니다. BEDROCK 은 SDK 가 엔드포인트를 해석합니다.
    endpoint_url: Mapped[str | None] = mapped_column(String(512))
    #: ADR-0003. 모델마다 노출 방언이 다를 수 있습니다. DB CHECK 로 빈 배열이 막혀 있습니다.
    supported_dialects: Mapped[list[ApiDialect]] = mapped_column(
        ARRAY(pg_enum(ApiDialect, "api_dialect", "model"))
    )
    status: Mapped[ModelStatus] = mapped_column(pg_enum(ModelStatus, "model_status", "model"))
    max_input_tokens: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    supports_streaming: Mapped[bool] = mapped_column(Boolean)


class ModelPricing(Base):
    """단가 시계열. 행은 수정되지 않고 새 행이 이전 구간을 닫습니다.

    유효 구간이 겹치지 않는 것은 DB 의 EXCLUDE 제약이 보장하므로, gateway 는 '지금 유효한
    1건'만 고르면 됩니다.
    """

    __tablename__ = "model_pricings"
    __table_args__ = {"schema": "model"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128))
    input_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    output_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    cache_write_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    cache_read_price_per_1k: Mapped[Decimal] = mapped_column(Numeric(14, 8))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeamAllowedModel(Base):
    """행이 0개면 카탈로그의 ACTIVE 전체 허용입니다."""

    __tablename__ = "team_allowed_models"
    __table_args__ = {"schema": "model"}

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)


class UserAllowedModel(Base):
    """행이 있으면 팀 정책을 덮어쓰고, 0개면 팀 정책으로 폴백합니다.

    0개가 '전체 허용'이 아니라는 점이 팀 층과 다릅니다. 이 비대칭이 3층 해석의 핵심입니다.
    """

    __tablename__ = "user_allowed_models"
    __table_args__ = {"schema": "model"}

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)


class RateLimitConfig(Base):
    """활성 행은 `(scope, COALESCE(scope_id, nil), COALESCE(model_alias, '*'))` 당 하나입니다.

    `scope_id` 가 NULL 인 것은 `GLOBAL` 뿐이고, `model_alias` 가 NULL 이면 그 scope 의 모든
    모델입니다. 세 한도는 각각 NULL 일 수 있으며 **NULL 은 "정의되지 않음"** 이라 해석에서
    다음 후보로 넘어갑니다(backend 06). 셋 다 NULL 인 행은 DB CHECK 가 막습니다.
    """

    __tablename__ = "rate_limit_configs"
    __table_args__ = {"schema": "model"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    scope: Mapped[RateLimitScope] = mapped_column(
        pg_enum(RateLimitScope, "rate_limit_scope", "model")
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    model_alias: Mapped[str | None] = mapped_column(String(128))
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    tpm_limit: Mapped[int | None] = mapped_column(Integer)
    concurrency_limit: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean)
