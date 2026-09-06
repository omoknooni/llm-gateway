"""OpenAI 호환 엔드포인트 (`/v1/chat/completions`, `/v1/models`).

준비 경로는 Anthropic 쪽과 같은 함수를 씁니다(`api/pipeline`). 인증·집행·기록이 방언에 따라
갈리지 않는다는 약속이 코드로 지켜지는 지점입니다.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from gateway.api.pipeline import (
    PreparedCall,
    prepare,
    record_rejection,
    record_usage,
    stream_with_finalize,
)
from gateway.core.context import STATE_AUTH
from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import TokenUsage
from gateway.dialects.errors import error_body, error_headers
from gateway.dialects.openai import OpenAIChatDialect
from gateway.services.streaming import StreamAccumulator, guard

logger = structlog.get_logger(__name__)
router = APIRouter()

DIALECT = OpenAIChatDialect()

#: 목록 응답의 소유자 표시. client 는 이 값을 보고 사내 게이트웨이임을 압니다.
OWNED_BY = "llm-gateway"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    try:
        call = await prepare(request, dialect=DIALECT, api_dialect=ApiDialect.OPENAI_CHAT)
    except GatewayError as err:
        record_rejection(request, err)
        return _error(err)

    if call.normalized.stream:
        return await _stream(request, call)
    return await _invoke(request, call)


@router.get("/v1/models")
async def list_models(request: Request) -> Response:
    """**VK 가 실제로 부를 수 있는 모델만** 반환합니다.

    전체 카탈로그를 노출하면 client 는 쓸 수 없는 모델을 보고 시도했다가 403 을 받습니다.
    목록과 집행이 같은 판단을 쓰게 합니다(docs/04).
    """
    auth = request.scope["state"][STATE_AUTH]
    app_state = request.app.state
    catalog = await app_state.model_resolver.active_aliases(
        redis=app_state.redis, session_factory=app_state.session_factory
    )
    # 허용 목록은 이미 3층 해석과 INACTIVE 제외를 거쳤습니다. 교집합은 방어적 재확인입니다.
    aliases = sorted(set(catalog) & set(auth.allowed_model_aliases))

    import json

    payload = {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "created": 0, "owned_by": OWNED_BY}
            for alias in aliases
        ],
    }
    return Response(
        content=json.dumps(payload, separators=(",", ":")), media_type="application/json"
    )


@router.get("/v1/models/{model_id:path}")
async def get_model(model_id: str, request: Request) -> Response:
    """단일 모델 조회. 허용 범위 밖이면 목록과 같은 답(없음)을 줍니다."""
    auth = request.scope["state"][STATE_AUTH]
    app_state = request.app.state

    if model_id not in auth.allowed_model_aliases:
        return _error(
            GatewayError(ErrorCode.MODEL_INACTIVE, f"Model '{model_id}' is not available")
        )

    try:
        model = await app_state.model_resolver.resolve(
            model_ref=model_id, redis=app_state.redis, session_factory=app_state.session_factory
        )
    except GatewayError as err:
        return _error(err)

    import json

    payload = {"id": model.alias, "object": "model", "created": 0, "owned_by": OWNED_BY}
    return Response(
        content=json.dumps(payload, separators=(",", ":")), media_type="application/json"
    )


async def _invoke(request: Request, call: PreparedCall) -> Response:
    try:
        response = await call.adapter.invoke(
            call.normalized, call.decision, end_user_id=call.auth.end_user_id
        )
    except GatewayError as err:
        # provider 호출이 시작된 뒤의 실패입니다. 토큰은 0 이라도 행은 남깁니다 —
        # 실패도 운영 관점에서는 중요한 신호입니다.
        record_usage(
            request,
            call,
            status="TIMEOUT" if err.code is ErrorCode.UPSTREAM_TIMEOUT else "ERROR",
            usage=TokenUsage(),
            ttft_ms=None,
            is_streaming=False,
            error_code=err.code.value,
        )
        return _error(err)

    record_usage(
        request,
        call,
        status="SUCCESS",
        usage=response.usage,
        ttft_ms=None,
        is_streaming=False,
    )
    return Response(
        content=DIALECT.response(response, model_alias=call.decision.model.alias),
        media_type="application/json",
    )


async def _stream(request: Request, call: PreparedCall) -> Response:
    settings = request.app.state.settings
    try:
        events = await call.adapter.invoke_stream(
            call.normalized, call.decision, end_user_id=call.auth.end_user_id
        )
    except GatewayError as err:
        record_usage(
            request,
            call,
            status="TIMEOUT" if err.code is ErrorCode.UPSTREAM_TIMEOUT else "ERROR",
            usage=TokenUsage(),
            ttft_ms=None,
            is_streaming=True,
            error_code=err.code.value,
        )
        return _error(err)

    accumulator = StreamAccumulator()
    guarded = guard(events, idle_timeout=settings.stream_idle_timeout, accumulator=accumulator)
    include_usage = bool((call.raw.get("stream_options") or {}).get("include_usage"))

    frames = DIALECT.stream(
        guarded, model_alias=call.decision.model.alias, include_usage=include_usage
    )
    return StreamingResponse(
        stream_with_finalize(frames, request=request, call=call, accumulator=accumulator),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def _error(err: GatewayError) -> Response:
    logger.info("request.rejected", code=err.code, outcome=err.outcome)
    return Response(
        content=error_body(ApiDialect.OPENAI_CHAT, err),
        status_code=err.status,
        headers={k.decode(): v.decode() for k, v in error_headers(err)},
    )
