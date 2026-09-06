"""Anthropic Messages 엔드포인트 (`/v1/messages`).

준비 경로는 두 방언이 공유합니다(`api/pipeline`). 이 파일에 남는 것은 직렬화뿐입니다.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from gateway.api.pipeline import PreparedCall, prepare
from gateway.core.dialect import ApiDialect
from gateway.core.errors import GatewayError
from gateway.dialects.anthropic import AnthropicMessagesDialect, new_message_id
from gateway.dialects.errors import error_body, error_headers
from gateway.services.streaming import StreamAccumulator, guard

logger = structlog.get_logger(__name__)
router = APIRouter()

DIALECT = AnthropicMessagesDialect()


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    try:
        call = await prepare(request, dialect=DIALECT, api_dialect=ApiDialect.ANTHROPIC_MESSAGES)
    except GatewayError as err:
        return _error(err)

    if call.normalized.stream:
        return await _stream(request, call)
    return await _invoke(call)


async def _invoke(call: PreparedCall) -> Response:
    try:
        response = await call.adapter.invoke(
            call.normalized, call.decision, end_user_id=call.auth.end_user_id
        )
    except GatewayError as err:
        return _error(err)

    if not response.response_id:
        # provider 가 id 를 주지 않는 경우가 있습니다. client SDK 는 id 를 기대합니다.
        response.response_id = new_message_id()

    return Response(
        content=DIALECT.response(response, model_alias=call.decision.model.alias),
        media_type="application/json",
    )


async def _stream(request: Request, call: PreparedCall) -> Response:
    settings = request.app.state.settings
    try:
        # 첫 이벤트 전에 실패를 확정합니다. 여기서 예외가 나면 아직 HTTP 상태로 답할 수 있습니다.
        events = await call.adapter.invoke_stream(
            call.normalized, call.decision, end_user_id=call.auth.end_user_id
        )
    except GatewayError as err:
        return _error(err)

    accumulator = StreamAccumulator()
    guarded = guard(events, idle_timeout=settings.stream_idle_timeout, accumulator=accumulator)

    return StreamingResponse(
        DIALECT.stream(guarded, model_alias=call.decision.model.alias),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            # 프록시가 SSE 를 버퍼링하면 첫 토큰이 끝까지 도착하지 않습니다.
            "x-accel-buffering": "no",
        },
    )


def _error(err: GatewayError) -> Response:
    logger.info("request.rejected", code=err.code, outcome=err.outcome)
    return Response(
        content=error_body(ApiDialect.ANTHROPIC_MESSAGES, err),
        status_code=err.status,
        headers={k.decode(): v.decode() for k, v in error_headers(err)},
    )
