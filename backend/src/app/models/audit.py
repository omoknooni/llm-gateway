"""audit 스키마 — control plane 감사 로그와 캐시 무효화 실패.

gateway 는 이 스키마에 접근하지 않습니다. 인증 성공/실패 이벤트는 data plane 의 사건이므로
여기가 아니라 `usage` 스키마가 받습니다(03 문서).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """control plane 의 모든 상태 변경 기록. 조회는 남기지 않습니다."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id", "occurred_at"),
        Index("ix_audit_logs_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_logs_occurred_at", "occurred_at"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 동사_명사. 예: CREATE_VIRTUAL_KEY
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    #: {"before": {...}, "after": {...}}. 비밀값은 절대 넣지 않습니다.
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[str] = mapped_column(String(16), nullable=False, server_default="SUCCESS")
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, server_default="")


class CacheInvalidationFailure(Base):
    """캐시 삭제 실패 기록. 업무 트랜잭션은 이미 커밋됐으므로 롤백하지 않고 여기에 남깁니다."""

    __tablename__ = "cache_invalidation_failures"
    __table_args__ = (
        Index("ix_cache_failures_unresolved", "resolved_at", "failed_at"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cache_key: Mapped[str] = mapped_column(String(512), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
