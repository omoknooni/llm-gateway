"""공통 응답 스키마."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str = Field(description="frontend 가 분기하는 안정 식별자")
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    """cursor 기반 페이지네이션 응답. offset 은 쓰지 않습니다."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
