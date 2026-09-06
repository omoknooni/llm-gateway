"""auth 스키마 — SELECT 전용. 예외는 `virtual_keys.last_used_at` 하나뿐입니다."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from gateway.schema.base import Base, VKOwnerType, VKStatus, pg_enum


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean)


class User(Base):
    """`idp_subject` 를 매핑하지 않는 것은 의도입니다.

    provider 로 내보낼 end-user 식별자를 `idp_subject`(OIDC sub)에서 `user_id` 로 바꿨습니다.
    IdP 설정에 따라 sub 에 이메일이나 사번이 들어올 수 있어, 불투명 식별자를 요구하는
    provider 규약을 만족한다고 보장할 수 없기 때문입니다(docs/06 Q4).
    읽지 않는 컬럼을 매핑해 두면 다음 사람이 "쓰라고 있는 값"으로 오해합니다.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean)


class VirtualKey(Base):
    __tablename__ = "virtual_keys"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    #: sha256(원문) 의 소문자 hex 64자. 인증 조회 키입니다(공유 계약 C1).
    key_hash: Mapped[str] = mapped_column(String(64))
    owner_type: Mapped[VKOwnerType] = mapped_column(pg_enum(VKOwnerType, "vk_owner_type", "auth"))
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: 비정규화 컬럼. USER 소유 키에도 항상 채워져 있어 요청 경로에서 팀 조회 조인이 필요 없습니다.
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[VKStatus] = mapped_column(pg_enum(VKStatus, "vk_status", "auth"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: gateway 가 쓰는 유일한 auth 컬럼. 분 단위 스로틀링으로만 씁니다.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VirtualKeyAllowedModel(Base):
    """VK 층 축소. 행이 0개면 '제한 없음'이 아니라 '축소 없음'입니다."""

    __tablename__ = "virtual_key_allowed_models"
    __table_args__ = {"schema": "auth"}

    virtual_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
