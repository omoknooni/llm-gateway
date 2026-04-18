from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TeamCreate(BaseModel):
    name: str
    description: str | None = None


class TeamRead(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    team_id: int | None = None


class UserRead(BaseModel):
    id: int
    email: EmailStr
    name: str
    team_id: int | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ModelCreate(BaseModel):
    alias: str
    provider: str = "bedrock"
    provider_model_id: str
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    active: bool = True


class ModelRead(BaseModel):
    id: int
    alias: str
    provider: str
    provider_model_id: str
    input_cost_per_1k: float
    output_cost_per_1k: float
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VirtualKeyCreate(BaseModel):
    owner_type: Literal["team", "user"] = "team"
    team_id: int | None = None
    user_id: int | None = None
    allowed_model_aliases: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class VirtualKeyRead(BaseModel):
    id: int
    key_prefix: str
    masked_key: str
    owner_type: str
    team_id: int | None
    user_id: int | None
    allowed_model_aliases: list[str]
    status: str
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    rotated_from_id: int | None

    class Config:
        from_attributes = True


class VirtualKeyCreateResponse(BaseModel):
    key: str
    record: VirtualKeyRead


class SyncResponse(BaseModel):
    synced: bool
    keys_pushed: int
    aliases_seen: int
    detail: str


class UsageSummary(BaseModel):
    total_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_estimated_cost_usd: float
    success_count: int
    failure_count: int


class LeaderboardEntry(BaseModel):
    label: str
    request_count: int
    total_tokens: int
    estimated_cost_usd: float


