"""두 방언이 공유하는 요청 준비 경로.

인증·정책 집행·기록은 방언과 무관하게 같은 경로를 지나야 합니다(ADR-0003). 그 "같은 경로"가
문서상의 약속이 아니라 **한 함수**가 되도록 여기에 모읍니다. 방언별 라우터는 파싱 결과를 받아
직렬화만 다르게 합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request

from gateway.core.context import STATE_AUTH, AuthContext
from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.model import ModelConfig
from gateway.core.normalized import NormalizedRequest
from gateway.core.routing import BackendDecision
from gateway.dialects.base import load_json
from gateway.providers.base import ProviderAdapter


class ParsingDialect(Protocol):
    def parse_data(
        self, data: dict[str, Any], *, default_max_tokens: int, model: ModelConfig | None
    ) -> NormalizedRequest: ...


@dataclass
class PreparedCall:
    auth: AuthContext
    normalized: NormalizedRequest
    decision: BackendDecision
    adapter: ProviderAdapter
    raw: dict[str, Any]


async def prepare(
    request: Request, *, dialect: ParsingDialect, api_dialect: ApiDialect
) -> PreparedCall:
    """DialectParse → ModelResolve → ScopeCheck → DialectCheck → adapter 선택.

    실패는 전부 `GatewayError` 로 올라오고, 방언별 라우터가 자기 형식으로 옮깁니다.
    """
    state = request.scope["state"]
    auth: AuthContext = state[STATE_AUTH]
    app_state = request.app.state
    settings = app_state.settings

    body = await read_body(request, settings.max_body_size)
    data = load_json(body)

    model_ref = data.get("model")
    if not isinstance(model_ref, str) or not model_ref:
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Field 'model' is required", param="model")

    # 모델을 먼저 해석하는 이유는 max_tokens 검증에 모델 상한이 필요해서입니다.
    # 같은 본문을 두 번 파싱하지 않으려고 dict 를 넘깁니다.
    decision = await app_state.router.decide(
        model_ref=model_ref,
        dialect=api_dialect,
        auth=auth,
        stream=bool(data.get("stream", False)),
        redis=app_state.redis,
        session_factory=app_state.session_factory,
    )
    normalized = dialect.parse_data(
        data, default_max_tokens=settings.default_max_output_tokens, model=decision.model
    )
    adapter = app_state.provider_registry.get(decision.provider)

    return PreparedCall(
        auth=auth, normalized=normalized, decision=decision, adapter=adapter, raw=data
    )


async def read_body(request: Request, limit: int) -> bytes:
    """본문 크기 상한.

    Content-Length 를 먼저 보는 이유는 헤더만으로 거절할 수 있으면 20MB 를 다 읽지 않아도 되기
    때문입니다. 헤더가 없거나 거짓일 수 있으므로 실제 길이도 확인합니다.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise GatewayError(ErrorCode.REQUEST_TOO_LARGE, "Request body is too large")
    body = await request.body()
    if len(body) > limit:
        raise GatewayError(ErrorCode.REQUEST_TOO_LARGE, "Request body is too large")
    return body
