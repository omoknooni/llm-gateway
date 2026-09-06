from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ServiceTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, description="용도 식별용 이름")
    expires_in_days: int = Field(default=90, ge=1, le=365)


class ServiceTokenResponse(BaseModel):
    id: str
    name: str
    token_prefix: str
    expires_at: datetime
    revoked_at: datetime | None = None
    rotated_from_id: str | None = None
    created_at: datetime


class ServiceTokenCreateResponse(ServiceTokenResponse):
    #: 원문은 발급·로테이션 응답에만 존재합니다. 이후 어떤 API 로도 다시 볼 수 없습니다.
    token: str
