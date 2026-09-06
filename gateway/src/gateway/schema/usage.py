"""usage 스키마 — gateway 가 INSERT 하는 두 테이블.

스키마는 backend 가 정의하고 **내용은 gateway 가 결정**합니다(공유 계약 C5).

기록 위치가 둘로 나뉩니다.

    provider 호출이 일어난 실패 (ERROR / TIMEOUT)  → usage_events
    정책이 막은 거절 (401 / 403 / 429)             → auth_events

거절을 `usage_events` 에 넣으면 토큰도 비용도 0인 행이 대량으로 쌓여 집계 쿼리가 전부
그것을 걸러내야 합니다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Uuid
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from gateway.schema.base import ApiDialect, Base, UsageStatus, pg_enum


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = {"schema": "usage"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    #: UNIQUE. 재시도가 중복 행을 만들지 않게 하는 멱등 키입니다.
    request_id: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: TEAM 소유 VK 호출은 사람에 귀속되지 않으므로 NULL 입니다.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    virtual_key_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    model_alias: Mapped[str] = mapped_column(String(128))
    provider_model_id: Mapped[str] = mapped_column(String(512))
    dialect: Mapped[ApiDialect] = mapped_column(pg_enum(ApiDialect, "api_dialect", "model"))
    status: Mapped[UsageStatus] = mapped_column(pg_enum(UsageStatus, "usage_status", "usage"))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_write_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_tokens: Mapped[int] = mapped_column(Integer)
    #: provider 가 usage 를 주지 않아 역산한 경우 true. 청구 정확도 분석의 근거입니다.
    estimated_usage: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    is_streaming: Mapped[bool] = mapped_column(Boolean)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    #: 어떤 단가로 계산했는지. 단가가 나중에 바뀌어도 되짚을 수 있어야 합니다.
    pricing_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(64))
    #: S3. 도구별 사용량 분해용 관측 라벨입니다.
    client: Mapped[str | None] = mapped_column(String(64))


class AuthEvent(Base):
    """정책 거절 기록 (S4).

    한 행이 창(window) 안의 N 건을 대표합니다. **조회는 행 수가 아니라
    `SUM(occurrence_count)`** 여야 합니다 — 창이 프로세스 로컬이라 pod 수만큼 행이 나뉩니다.
    """

    __tablename__ = "auth_events"
    __table_args__ = {"schema": "usage"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    #: 창의 마지막 실패 시각.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(64))
    virtual_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: sha256(원문) 의 앞 8자. `virtual_keys.key_prefix`(원문 표시값)와 **다른 값**입니다.
    #: 미등록 키를 묶어 보기 위한 것이고, 32비트로는 원문을 복원할 수 없습니다.
    key_hash_prefix: Mapped[str | None] = mapped_column(String(8))
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    client: Mapped[str | None] = mapped_column(String(64))
    model_alias: Mapped[str | None] = mapped_column(String(128))
    source_ip: Mapped[str | None] = mapped_column(INET)
    #: 창의 **첫** 요청 id. 그 요청의 로그 줄이 원인을 담고 있어 조사 진입점이 됩니다.
    request_id: Mapped[str] = mapped_column(String(128))
