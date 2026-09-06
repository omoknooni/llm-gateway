"""애플리케이션 예외.

`code` 는 frontend 가 분기하는 안정 식별자입니다(00 문서 Error Contract).
임의로 바꾸지 않습니다.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}
        super().__init__(message)


class ValidationError(AppError):
    status_code = 400
    code = "validation_error"


class UnauthenticatedError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"

    def __init__(self, message: str = "권한이 없습니다", **kwargs):
        super().__init__(message, **kwargs)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, resource: str, identifier: str, **kwargs):
        super().__init__(f"{resource} 를 찾을 수 없습니다: {identifier}", **kwargs)


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class InvalidStateTransitionError(ConflictError):
    code = "invalid_state_transition"
