import pytest

from gateway.core.errors import ErrorCode, GatewayError, status_for


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.INVALID_VIRTUAL_KEY, 401),
        (ErrorCode.MODEL_NOT_ALLOWED, 403),
        (ErrorCode.MODEL_INACTIVE, 404),
        (ErrorCode.BUDGET_EXCEEDED, 429),
        (ErrorCode.RATE_LIMIT_EXCEEDED, 429),
        (ErrorCode.DIALECT_NOT_SUPPORTED, 400),
        (ErrorCode.UNSUPPORTED_FIELD, 400),
        (ErrorCode.INVALID_REQUEST, 400),
        (ErrorCode.REQUEST_TOO_LARGE, 413),
        (ErrorCode.PROVIDER_ERROR, 502),
        (ErrorCode.UPSTREAM_TIMEOUT, 504),
        (ErrorCode.DEPENDENCY_UNAVAILABLE, 503),
    ],
)
def test_c6_status_mapping(code: ErrorCode, status: int):
    """공유 계약 C6 의 상태 코드. 여기가 바뀌면 두 방언의 응답이 함께 바뀝니다."""
    assert status_for(code) == status
    assert GatewayError(code, "x").status == status


def test_every_code_has_a_status():
    for code in ErrorCode:
        assert status_for(code) > 0
