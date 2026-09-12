"""공통 응답 스키마."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

T = TypeVar("T")

#: 금액·비율은 문자열로 직렬화합니다(00 문서 공통 타입 규약).
#: JSON number 로 내보내면 프론트의 IEEE754 로 옮겨지면서 정밀도가 조용히 깨집니다.
DecimalStr = Annotated[Decimal, PlainSerializer(str, return_type=str, when_used="json")]


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
