"""내부 오류 코드를 방언별 오류 응답으로 옮깁니다.

**내부 구분은 유지하고 표현만 바꿉니다**(ADR-0003). 같은 `ErrorCode` 가 `usage_events.error_code`
와 `auth_events.outcome` 매핑에도 쓰이므로, 여기서 코드를 뭉개면 관측이 함께 뭉개집니다.

provider 원문 메시지는 여기까지 오지 않습니다. 계정 ID·ARN·내부 엔드포인트가 섞여 나오므로
client 에는 분류된 메시지를, 로그에는 원문을 남깁니다(docs/01).
"""

from __future__ import annotations

import json

from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError

#: docs/01 의 에러 매핑표. 변경은 두 방언 응답을 동시에 바꾸므로 표와 함께 갱신합니다.
_ANTHROPIC_TYPE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_VIRTUAL_KEY: "authentication_error",
    ErrorCode.MODEL_NOT_ALLOWED: "permission_error",
    ErrorCode.MODEL_INACTIVE: "not_found_error",
    ErrorCode.BUDGET_EXCEEDED: "rate_limit_error",
    ErrorCode.RATE_LIMIT_EXCEEDED: "rate_limit_error",
    ErrorCode.DIALECT_NOT_SUPPORTED: "invalid_request_error",
    ErrorCode.UNSUPPORTED_FIELD: "invalid_request_error",
    ErrorCode.INVALID_REQUEST: "invalid_request_error",
    ErrorCode.REQUEST_TOO_LARGE: "request_too_large",
    ErrorCode.PROVIDER_ERROR: "api_error",
    ErrorCode.UPSTREAM_TIMEOUT: "api_error",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "overloaded_error",
}

_OPENAI_TYPE: dict[ErrorCode, str] = {
    ErrorCode.INVALID_VIRTUAL_KEY: "authentication_error",
    ErrorCode.MODEL_NOT_ALLOWED: "permission_error",
    ErrorCode.MODEL_INACTIVE: "invalid_request_error",
    ErrorCode.BUDGET_EXCEEDED: "rate_limit_error",
    ErrorCode.RATE_LIMIT_EXCEEDED: "rate_limit_error",
    ErrorCode.DIALECT_NOT_SUPPORTED: "invalid_request_error",
    ErrorCode.UNSUPPORTED_FIELD: "invalid_request_error",
    ErrorCode.INVALID_REQUEST: "invalid_request_error",
    ErrorCode.REQUEST_TOO_LARGE: "invalid_request_error",
    ErrorCode.PROVIDER_ERROR: "server_error",
    ErrorCode.UPSTREAM_TIMEOUT: "server_error",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "server_error",
}

#: OpenAI 스키마의 `code` 는 관례적으로 쓰이는 값이 따로 있는 경우가 있습니다.
_OPENAI_CODE_OVERRIDE: dict[ErrorCode, str] = {
    ErrorCode.MODEL_INACTIVE: "model_not_found",
}


def error_body(dialect: ApiDialect, err: GatewayError) -> bytes:
    if dialect is ApiDialect.ANTHROPIC_MESSAGES:
        payload = {
            "type": "error",
            "error": {"type": _ANTHROPIC_TYPE[err.code], "message": err.message},
        }
    else:
        payload = {
            "error": {
                "message": err.message,
                "type": _OPENAI_TYPE[err.code],
                "param": err.param,
                "code": _OPENAI_CODE_OVERRIDE.get(err.code, err.code.value),
            }
        }
    return json.dumps(payload, separators=(",", ":")).encode()


def error_headers(err: GatewayError) -> list[tuple[bytes, bytes]]:
    headers = [(b"content-type", b"application/json")]
    if err.retry_after is not None:
        # 429 는 언제 다시 오면 되는지 알려줘야 client 가 즉시 재시도로 폭주하지 않습니다.
        headers.append((b"retry-after", str(err.retry_after).encode()))
    return headers


async def send_error(send, dialect: ApiDialect, err: GatewayError) -> None:
    """라우팅 전(미들웨어)에서 오류를 내보냅니다.

    라우터 안에서는 FastAPI 응답을 쓰지만, 미들웨어는 ASGI `send` 를 직접 다뤄야 합니다.
    """
    body = error_body(dialect, err)
    await send(
        {"type": "http.response.start", "status": err.status, "headers": error_headers(err)}
    )
    await send({"type": "http.response.body", "body": body})
