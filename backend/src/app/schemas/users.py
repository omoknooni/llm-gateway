from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole


class UserCreateRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.MEMBER
    team_id: str | None = None

    @field_validator("display_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("공백만으로 구성될 수 없습니다")
        return stripped


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None


class UserTeamTransferRequest(BaseModel):
    #: null 이면 팀 해제.
    team_id: str | None = None
    reason: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: UserRole
    team_id: str | None = None
    provider: str
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserTransferResponse(BaseModel):
    """정책이 언제 반영되는지 화면이 바로 알 수 있어야 합니다(02 문서)."""

    user_id: str
    team_id: str | None
    previous_team_id: str | None
    affected_virtual_keys: int
    cache_invalidated: bool


class UserDeactivateResponse(BaseModel):
    user_id: str
    revoked_virtual_keys: int
    cache_invalidated: bool


class OrgTreeMember(BaseModel):
    id: str
    display_name: str
    email: str
    role: UserRole
    is_active: bool


class OrgTreeTeam(BaseModel):
    id: str
    name: str
    is_active: bool
    leader_user_id: str | None = None
    members: list[OrgTreeMember]
