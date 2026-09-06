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
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import INET
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
    #: 요청을 보낸 도구. 인가 신호가 아니라 관측 라벨입니다(위조 가능한 헤더에서 옵니다).
    #: 값 집합은 gateway 설정의 화이트리스트로 제한되고, 미등록 값은 'other' 로 떨어집니다.
    client: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuthEvent(Base):
    """정책 거절 기록. **gateway 가 INSERT** 하고 backend 는 읽기만 합니다.

    provider 호출이 일어난 실패(`ERROR`/`TIMEOUT`)는 `usage_events` 로, 정책이 막은 거절
    (401/403/429)은 이 테이블로 갑니다. 후자를 `usage_events` 에 넣으면 토큰도 비용도 0인 행이
    대량으로 쌓여 모든 집계 쿼리가 그것을 걸러내야 합니다.

    control plane 감사(`audit.audit_logs`)와도 분리됩니다. 저 QPS 테이블에 고 QPS 쓰기를
    넣지 않기 위해서입니다(03 문서).

    gateway 는 동일 출처의 연속 실패를 60초 창으로 묶어 **한 행으로** 기록합니다. 따라서
    조회 시 행 수가 아니라 `SUM(occurrence_count)` 를 써야 합니다. 창은 프로세스 로컬이라
    pod 수만큼 행이 나뉘고, 행 수로 세면 실패가 과소 계상됩니다.
    """

    __tablename__ = "auth_events"
    __table_args__ = (
        CheckConstraint("occurrence_count >= 1", name="ck_auth_events_count_positive"),
        CheckConstraint("occurred_at >= first_occurred_at", name="ck_auth_events_window_order"),
        Index("ix_auth_events_occurred_at", "occurred_at"),
        Index("ix_auth_events_vk_occurred", "virtual_key_id", "occurred_at"),
        Index("ix_auth_events_hash_prefix_occurred", "key_hash_prefix", "occurred_at"),
        {"schema": "usage"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    #: 창의 마지막 실패 시각.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 창의 첫 실패 시각.
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 창 안의 실패 수. 1건뿐이어도 1 입니다.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    #: 거절 사유. enum 이 아니라 text 입니다 — 값이 늘 때마다 backend 마이그레이션을 기다리면
    #: "내용은 gateway 가 결정한다"(C5)가 뒤집힙니다. 알려진 값 집합은 09 문서에 고정합니다.
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    virtual_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.virtual_keys.id"), nullable=True
    )
    #: `sha256(원문)` 의 앞 8자. `virtual_keys.key_prefix`(원문의 표시용 앞부분)와 **다른 값**입니다.
    #: 미등록 키의 반복 실패를 묶어 보기 위한 것이고, 32비트로는 원문을 복원할 수 없습니다.
    key_hash_prefix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.teams.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.users.id"), nullable=True
    )
    client: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 카탈로그에 없는 alias 로 거절된 경우도 있으므로 **FK 를 걸지 않습니다.**
    model_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    #: 창의 **첫** 요청 id. 그 요청의 로그 라인이 원인을 담고 있어 조사 진입점이 됩니다.
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)


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
