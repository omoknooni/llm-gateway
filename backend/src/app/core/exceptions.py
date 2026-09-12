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


class CounterWriteError(AppError):
    """집행 카운터(Redis)를 갱신하지 못했습니다.

    503 인 이유는 요청이 잘못된 것이 아니라 의존 저장소가 응답하지 않은 것이기 때문입니다.
    호출자가 그대로 재시도하면 됩니다 — 재시드는 멱등합니다.
    """

    status_code = 503
    code = "counter_write_failed"
