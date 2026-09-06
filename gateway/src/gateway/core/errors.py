"""내부 오류 코드.

공유 계약 C6 이 정의한 코드입니다. gateway 가 각 방언의 오류 형식으로 변환하더라도 **내부
구분은 유지**하며(ADR-0003), 같은 값이 `usage_events.error_code` 와 `auth_events.outcome`
매핑에도 쓰입니다. 방언별 표현은 `dialects/` 가 담당하고 여기에는 코드와 상태만 둡니다.
"""

from __future__ import annotations

from enum import StrEnum


class AuthOutcome(StrEnum):
    """`usage.auth_events.outcome` 의 값 집합 (공유 계약, docs/06 S4).

    `outcome` 컬럼은 enum 이 아니라 text 입니다 — 값이 늘 때마다 backend 마이그레이션을 기다리면
    "내용은 gateway 가 결정한다"(C5)가 뒤집히기 때문입니다. 대신 값 집합을 여기서 고정합니다.
    """

    INVALID_KEY = "INVALID_KEY"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    OWNER_INACTIVE = "OWNER_INACTIVE"
    MODEL_NOT_ALLOWED = "MODEL_NOT_ALLOWED"
    MODEL_INACTIVE = "MODEL_INACTIVE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"


class ErrorCode(StrEnum):
    INVALID_VIRTUAL_KEY = "invalid_virtual_key"
    MODEL_NOT_ALLOWED = "model_not_allowed"
    MODEL_INACTIVE = "model_inactive"
    BUDGET_EXCEEDED = "budget_exceeded"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    DIALECT_NOT_SUPPORTED = "dialect_not_supported"
    UNSUPPORTED_FIELD = "unsupported_field"
    INVALID_REQUEST = "invalid_request"
    REQUEST_TOO_LARGE = "request_too_large"
    PROVIDER_ERROR = "provider_error"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_VIRTUAL_KEY: 401,
    ErrorCode.MODEL_NOT_ALLOWED: 403,
    ErrorCode.MODEL_INACTIVE: 404,
    ErrorCode.BUDGET_EXCEEDED: 429,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    ErrorCode.DIALECT_NOT_SUPPORTED: 400,
    ErrorCode.UNSUPPORTED_FIELD: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.REQUEST_TOO_LARGE: 413,
    ErrorCode.PROVIDER_ERROR: 502,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
}


class GatewayError(Exception):
    """방언 중립 오류.

    `message` 는 client 에게 그대로 보이므로 provider 원문을 담지 않습니다. 계정 ID·ARN·내부
    엔드포인트가 섞여 나옵니다. 원문은 로그에만 남깁니다(docs/01).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retry_after: int | None = None,
        param: str | None = None,
        outcome: AuthOutcome | None = None,
        key_hash_prefix: str | None = None,
        model_alias: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.param = param
        # 아래 셋은 **기록 힌트**입니다. 거절을 `usage.auth_events` 에 남길 때 쓰이고
        # client 응답에는 나가지 않습니다.
        #: 값이 있으면 기록될 거절입니다. None 이면 기록하지 않습니다(요청 자체가 잘못됐거나
        #: 의존성 장애 — docs/01 의 기록 위치 표).
        self.outcome = outcome
        #: sha256(원문) 의 앞 8자. 미등록 키를 묶어 보기 위한 값이고 원문 복원에 쓸 수 없습니다.
        #: `virtual_keys.key_prefix`(원문 표시값)와 다른 값입니다.
        self.key_hash_prefix = key_hash_prefix
        #: 모델 단계에서 막힌 거절이 어느 alias 였는지.
        self.model_alias = model_alias

    @property
    def status(self) -> int:
        return _STATUS[self.code]

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"GatewayError({self.code}, {self.message!r})"


def status_for(code: ErrorCode) -> int:
    return _STATUS[code]
