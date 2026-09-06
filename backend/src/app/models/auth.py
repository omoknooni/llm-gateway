"""auth 스키마 — 팀, 사용자, 관리자 인증, Virtual Key.

gateway 는 이 스키마를 SELECT 하고 `virtual_keys.last_used_at` 만 UPDATE 합니다(08 문서 C4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import UserRole, VKOwnerType, VKStatus, pg_enum
from app.models.mixins import TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 순환 FK(teams ↔ users). use_alter 로 테이블 생성 후 제약을 겁니다.
    leader_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.users.id", use_alter=True, name="fk_teams_leader_user_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    members: Mapped[list[User]] = relationship(
        back_populates="team", foreign_keys="User.team_id", lazy="raise"
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_team_id_active", "team_id", postgresql_where=text("is_active")),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role", "auth"), nullable=False, default=UserRole.MEMBER
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.teams.id"), nullable=True
    )
    # OIDC sub claim. 관리자가 먼저 생성한 직후에는 NULL 이고, 첫 로그인 시 채워집니다.
    idp_subject: Mapped[str | None] = mapped_column(String(512), nullable=True, unique=True)
    # 주체 출처. 다중 IdP 운영 시 식별자. 예: 'oidc:keycloak'
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="local", server_default="local"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped[Team | None] = relationship(
        back_populates="members", foreign_keys=[team_id], lazy="raise"
    )


class AdminJWTConfig(Base, TimestampMixin):
    """관리자 토큰 검증용 공개키. 비밀키는 저장하지 않습니다."""

    __tablename__ = "admin_jwt_configs"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    audience: Mapped[str] = mapped_column(String(512), nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(16), nullable=False, default="RS256")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ServiceToken(Base):
    """외부 시스템·배치용 토큰. 원문은 저장하지 않고 sha256 해시만 둡니다."""

    __tablename__ = "service_tokens"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.service_tokens.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VirtualKey(Base, TimestampMixin):
    """Virtual Key.

    **원문도 암호문도 저장하지 않습니다.** `key_hash = sha256(raw_key)` 와 표시용 prefix 만
    둡니다(03 문서). gateway 는 같은 해시로 조회하고 `last_used_at` 만 UPDATE 합니다.
    """

    __tablename__ = "virtual_keys"
    __table_args__ = (
        Index("ix_virtual_keys_owner", "owner_type", "owner_id"),
        Index("ix_virtual_keys_team_status", "team_id", "status"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_type: Mapped[VKOwnerType] = mapped_column(
        pg_enum(VKOwnerType, "vk_owner_type", "auth"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # 집계·인가용 비정규화. USER 소유여도 소속 팀을 고정합니다(요청 경로에서 조인 제거).
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.teams.id"), nullable=False)
    status: Mapped[VKStatus] = mapped_column(
        pg_enum(VKStatus, "vk_status", "auth"), nullable=False, default=VKStatus.ACTIVE
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: gateway 가 쓰는 유일한 auth 컬럼. 분 단위 스로틀링으로 씁니다.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.virtual_keys.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("auth.users.id"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)


class VirtualKeyAllowedModel(Base):
    """VK 단위 허용 모델 축소. 행이 0개면 '축소 없음'입니다(허용 전체가 아닙니다)."""

    __tablename__ = "virtual_key_allowed_models"
    __table_args__ = {"schema": "auth"}

    virtual_key_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth.virtual_keys.id", ondelete="CASCADE"), primary_key=True
    )
    model_alias: Mapped[str] = mapped_column(
        String(128), ForeignKey("model.model_aliases.alias"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "AdminJWTConfig",
    "ServiceToken",
    "Team",
    "User",
    "VirtualKey",
    "VirtualKeyAllowedModel",
]
