"""방언 계층의 경계.

방언은 **파싱과 직렬화에만** 존재합니다. 인증·정책 집행·기록은 방언과 무관하게 같은 경로를
지납니다(ADR-0003).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol

from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.model import ModelConfig
from gateway.core.normalized import NormalizedRequest, ProviderResponse, StreamEvent


class Dialect(Protocol):
    dialect: ApiDialect

    def parse(self, body: bytes, *, default_max_tokens: int) -> NormalizedRequest: ...

    def response(self, response: ProviderResponse, *, model_alias: str) -> bytes: ...

    def stream(
        self, events: AsyncIterator[StreamEvent], *, model_alias: str
    ) -> AsyncIterator[bytes]: ...


def load_json(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except Exception as exc:
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Request body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Request body must be a JSON object")
    return data


def reject_unknown_fields(data: dict[str, Any], accepted: Iterable[str]) -> None:
    """미지원 필드는 조용히 무시하지 않고 거절합니다.

    무시하면 client 는 적용됐다고 오해하고, 그 오해가 비용과 품질 문제로 돌아옵니다.
    거절 메시지에 필드 이름을 담아야 client 가 고칠 수 있습니다(docs/01).
    """
    unknown = sorted(set(data) - set(accepted))
    if unknown:
        raise GatewayError(
            ErrorCode.UNSUPPORTED_FIELD,
            f"Unsupported field: {', '.join(repr(f) for f in unknown)}",
            param=unknown[0],
        )


def require(data: dict[str, Any], field: str) -> Any:
    if field not in data or data[field] is None:
        raise GatewayError(
            ErrorCode.INVALID_REQUEST, f"Field '{field}' is required", param=field
        )
    return data[field]


def resolve_max_tokens(
    requested: int | None, model: ModelConfig | None, default_max_tokens: int
) -> int:
    """모델 상한을 넘는 요청은 잘라서 보내지 않고 거절합니다.

    잘라 보내면 client 는 잘린 줄 모르고 응답이 짧은 이유를 모델 탓으로 돌립니다.
    """
    limit = (model.max_output_tokens if model else None) or default_max_tokens
    if requested is None:
        return limit
    if requested <= 0:
        raise GatewayError(
            ErrorCode.INVALID_REQUEST, "max_tokens must be positive", param="max_tokens"
        )
    if model and model.max_output_tokens and requested > model.max_output_tokens:
        raise GatewayError(
            ErrorCode.INVALID_REQUEST,
            f"max_tokens {requested} exceeds the limit of {model.max_output_tokens} "
            f"for model '{model.alias}'",
            param="max_tokens",
        )
    return requested


def sse(event: str, payload: dict[str, Any]) -> bytes:
    """SSE 한 프레임.

    Anthropic 은 `event:` 줄을 요구하고 OpenAI 는 무시합니다. 이름을 붙여 두면 두 방언이
    같은 헬퍼를 씁니다.
    """
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()
