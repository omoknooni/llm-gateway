from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _strip(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("공백만으로 구성될 수 없습니다")
    return stripped


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None

    _normalize = field_validator("name")(_strip)


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        return _strip(value) if value is not None else None


class TeamLeaderRequest(BaseModel):
    #: null 이면 팀장 해제.
    user_id: str | None = None


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    leader_user_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
