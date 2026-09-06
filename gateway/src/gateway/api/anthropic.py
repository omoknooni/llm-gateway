"""Anthropic Messages 엔드포인트 (`/v1/messages`).

라우터의 일은 순서를 지키는 것입니다.

    DialectParse → ModelResolve → DialectCheck → ScopeCheck → Invoke → Serialize → Finalize

앞의 넷은 provider 를 모르고, Invoke 는 방언을 모릅니다. 이 두 방향의 무지가 설계의 핵심입니다.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from gateway.core.context import STATE_AUTH
from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import ProviderResponse
from gateway.dialects.anthropic import AnthropicMessagesDialect, new_message_id
from gateway.dialects.base import load_json
from gateway.dialects.errors import error_body, error_headers
from gateway.services.streaming import StreamAccumulator, guard

logger = structlog.get_logger(__name__)
router = APIRouter()

DIALECT = AnthropicMessagesDialect()


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    state = request.scope["state"]
    auth = state[STATE_AUTH]
    app_state = request.app.state
    settings = app_state.settings

    try:
        body = await _read_body(request, settings.max_body_size)
        data = load_json(body)

        # 모델을 먼저 해석하는 이유는 max_tokens 검증에 모델 상한이 필요해서입니다.
        # 같은 본문을 두 번 파싱하지 않으려고 dict 를 넘깁니다.
        model_ref = data.get("model")
        if not isinstance(model_ref, str) or not model_ref:
            raise GatewayError(
                ErrorCode.INVALID_REQUEST, "Field 'model' is required", param="model"
            )
        stream = bool(data.get("stream", False))

        decision = await app_state.router.decide(
            model_ref=model_ref,
            dialect=ApiDialect.ANTHROPIC_MESSAGES,
            auth=auth,
            stream=stream,
            redis=app_state.redis,
            session_factory=app_state.session_factory,
        )
        normalized = DIALECT.parse_data(
            data,
            default_max_tokens=settings.default_max_output_tokens,
            model=decision.model,
        )
        adapter = app_state.provider_registry.get(decision.provider)
    except GatewayError as err:
        return _error(err)

    if normalized.stream:
        return await _stream(request, adapter, normalized, decision, auth)
    return await _invoke(adapter, normalized, decision, auth)


async def _invoke(adapter, normalized, decision, auth) -> Response:
    try:
        response: ProviderResponse = await adapter.invoke(
            normalized, decision, end_user_id=auth.end_user_id
        )
    except GatewayError as err:
        return _error(err)

    if not response.response_id:
        # provider 가 id 를 주지 않는 경우가 있습니다. client SDK 는 id 를 기대합니다.
        response.response_id = new_message_id()

    return Response(
        content=DIALECT.response(response, model_alias=decision.model.alias),
        media_type="application/json",
    )


async def _stream(request: Request, adapter, normalized, decision, auth) -> Response:
    settings = request.app.state.settings
    try:
        # 첫 이벤트 전에 실패를 확정합니다. 여기서 예외가 나면 아직 HTTP 상태로 답할 수 있습니다.
        events = await adapter.invoke_stream(normalized, decision, end_user_id=auth.end_user_id)
    except GatewayError as err:
        return _error(err)

    accumulator = StreamAccumulator()
    guarded = guard(events, idle_timeout=settings.stream_idle_timeout, accumulator=accumulator)
    frames = DIALECT.stream(guarded, model_alias=decision.model.alias)

    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            # 프록시가 SSE 를 버퍼링하면 첫 토큰이 끝까지 도착하지 않습니다.
            "x-accel-buffering": "no",
        },
    )


async def _read_body(request: Request, limit: int) -> bytes:
    """본문 크기 상한.

    Content-Length 를 먼저 보는 이유는, 헤더만으로 거절할 수 있으면 20MB 를 다 읽지 않아도
    되기 때문입니다. 헤더가 없거나 거짓일 수 있으므로 실제 길이도 확인합니다.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise GatewayError(ErrorCode.REQUEST_TOO_LARGE, "Request body is too large")
    body = await request.body()
    if len(body) > limit:
        raise GatewayError(ErrorCode.REQUEST_TOO_LARGE, "Request body is too large")
    return body


def _error(err: GatewayError) -> JSONResponse:
    logger.info("request.rejected", code=err.code, outcome=err.outcome)
    return Response(
        content=error_body(ApiDialect.ANTHROPIC_MESSAGES, err),
        status_code=err.status,
        headers={k.decode(): v.decode() for k, v in error_headers(err)},
    )
