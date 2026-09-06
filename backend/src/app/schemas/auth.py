from __future__ import annotations

from pydantic import BaseModel


class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str
    team_id: str | None = None
    is_service_token: bool = False
