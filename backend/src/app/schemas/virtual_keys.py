from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import VKOwnerType, VKStatus
from app.policy.virtual_key import RevokeReason


class VirtualKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="운영자가 알아보는 이름")
    owner_type: VKOwnerType
    owner_id: str
    #: 필수입니다. 무기한 키는 API 로 만들 수 없습니다(03 문서).
    expires_at: datetime
    #: 비우면 소유자 정책을 그대로 씁니다("축소 없음"). 소유자 정책보다 넓힐 수는 없습니다.
    allowed_model_aliases: list[str] = Field(default_factory=list)


class VirtualKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    allowed_model_aliases: list[str] | None = None
    #: 단축만 허용합니다. 연장하려면 새 키를 발급합니다.
    expires_at: datetime | None = None


class VirtualKeyRotateRequest(BaseModel):
    grace_period_hours: int = Field(default=24, ge=0, le=168, description="구 키가 살아 있는 유예 시간")
    reason: str | None = None


class VirtualKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    owner_type: VKOwnerType
    owner_id: str
    team_id: str
    status: VKStatus
    expires_at: datetime | None
    last_used_at: datetime | None
    rotated_from_id: str | None
    revoked_at: datetime | None
    revoke_reason: str | None
    allowed_model_aliases: list[str]
    created_at: datetime
    updated_at: datetime


class VirtualKeyCreateResponse(VirtualKeyResponse):
    #: **발급과 로테이션 응답에만** 존재합니다. 이후 어떤 API 로도 다시 조회할 수 없습니다.
    virtual_key: str


class TeamRevokeAllRequest(BaseModel):
    #: 되돌릴 수 없고 client 가 즉시 깨지는 조작이라 팀 이름 확인을 요구합니다.
    confirm_team_name: str
    reason: RevokeReason = RevokeReason.INCIDENT


class TeamRevokeAllResponse(BaseModel):
    team_id: str
    revoked_virtual_keys: int
    cache_invalidated: bool


class VirtualKeyAuditEntry(BaseModel):
    occurred_at: datetime
    actor_user_id: str
    actor_role: str
    action: str
    resource_id: str
    changes: dict
    result: str


class VirtualKeyAuditResponse(BaseModel):
    key_id: str
    #: 조상 방향 로테이션 체인. "이 키의 조상은 무엇이고 왜 교체됐는가"가 한 화면에 보여야 합니다.
    rotation_chain: list[str]
    entries: list[VirtualKeyAuditEntry]
