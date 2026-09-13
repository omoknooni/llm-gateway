"""두 방언이 공유하는 요청 준비 경로.

인증·정책 집행·기록은 방언과 무관하게 같은 경로를 지나야 합니다(ADR-0003). 그 "같은 경로"가
문서상의 약속이 아니라 **한 함수**가 되도록 여기에 모읍니다. 방언별 라우터는 파싱 결과를 받아
직렬화만 다르게 합니다.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request

from gateway.core.context import STATE_AUTH, STATE_REQUEST, AuthContext, RequestContext
from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.model import ModelConfig
from gateway.core.normalized import NormalizedRequest, TokenUsage
from gateway.core.routing import BackendDecision
from gateway.dialects.base import load_json
from gateway.providers.base import ProviderAdapter
from gateway.services.budget_service import BudgetOutcome
from gateway.services.rate_limit_service import Reservation
from gateway.services.streaming import StreamAccumulator
from gateway.services.usage_recorder import build_record, calculate_cost


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
    dialect: ApiDialect
    #: 4a 의 산출물. 누적 경로가 한도 스냅샷을 여기서 읽습니다(docs/08).
    budget: BudgetOutcome
    #: 4b 가 잡아 둔 자원. `finalize` 가 정산·반납합니다.
    reservation: Reservation


async def prepare(
    request: Request, *, dialect: ParsingDialect, api_dialect: ApiDialect
) -> PreparedCall:
    """DialectParse → ModelResolve → ScopeCheck → DialectCheck → Budget → RateLimit → adapter.

    실패는 전부 `GatewayError` 로 올라오고, 방언별 라우터가 자기 형식으로 옮깁니다.

    **집행이 여기 있는 이유**는 미들웨어가 `model_alias` 와 `max_tokens` 를 모르기 때문입니다.
    둘 다 본문을 파싱해야 알 수 있고, 미들웨어에서 본문을 읽으면 라우터가 다시 읽지 못합니다
    (docs/08). 예산(읽기 전용)을 rate limit(카운터 증가)보다 먼저 보는 것도 계약입니다 —
    어차피 막힐 요청이 rate limit 윈도를 소모하면 안 됩니다.
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

    # 4a. 예산 — 읽기만 합니다.
    budget = await app_state.budget_service.evaluate(
        auth=auth, redis=app_state.redis, session_factory=app_state.session_factory
    )
    app_state.budget_service.enforce(budget)

    # 4b. rate limit — 여기서부터 카운터가 움직입니다.
    reservation = await app_state.rate_limits.charge(
        auth=auth,
        request=normalized,
        model_alias=decision.model.alias,
        redis=app_state.redis,
        session_factory=app_state.session_factory,
    )

    try:
        adapter = app_state.provider_registry.get(decision.provider)
    except GatewayError:
        # 슬롯을 잡아 놓고 나가면 게이지가 샙니다. 잡은 뒤의 모든 실패 경로가 반납을 지나야
        # 합니다.
        await app_state.rate_limits.finalize(app_state.redis, reservation, actual_tokens=None)
        raise

    return PreparedCall(
        auth=auth,
        normalized=normalized,
        decision=decision,
        adapter=adapter,
        raw=data,
        dialect=api_dialect,
        budget=budget,
        reservation=reservation,
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


# ── 기록 ──
#
# 기록 위치가 둘로 나뉩니다(docs/01 의 표).
#
#     provider 호출이 일어난 실패 (ERROR / TIMEOUT)  → usage_events
#     정책이 막은 거절 (401 / 403 / 429)             → auth_events
#     요청 자체가 잘못됨 (문법·크기·미지원 필드)      → 기록 없음, 로그와 메트릭만


def record_usage(
    request: Request,
    call: PreparedCall,
    *,
    status: str,
    usage: TokenUsage,
    ttft_ms: int | None,
    is_streaming: bool,
    error_code: str | None = None,
) -> None:
    """파이프라인 7단계(Finalize).

    사용량 기록에 더해 **예산 누적·tpm 정산·동시성 반납**이 여기서 일어납니다. 셋을 흩어
    놓으면 어느 한 경로(스트림 중단, provider 실패)가 그중 하나를 빠뜨립니다. 성공·실패·중단이
    모두 한 자리를 지나야 누락이 없습니다(docs/08).

    쓰기는 응답을 반환한 뒤 백그라운드로 나갑니다. 기록 실패가 client 응답에 영향을 주지
    않습니다.
    """
    ctx: RequestContext = request.scope["state"][STATE_REQUEST]
    app_state = request.app.state
    app_state.background.spawn(
        _finalize_enforcement(request, call, usage), name="enforcement_finalize"
    )
    record = build_record(
        request_id=ctx.request_id,
        auth=call.auth,
        decision=call.decision,
        dialect=call.dialect.value,
        status=status,
        usage=usage,
        latency_ms=ctx.elapsed_ms,
        ttft_ms=ttft_ms,
        is_streaming=is_streaming,
        error_code=error_code,
        client=ctx.client,
    )
    app_state.background.spawn(
        app_state.usage_recorder.record(app_state.session_factory, record), name="usage"
    )


async def _finalize_enforcement(
    request: Request, call: PreparedCall, usage: TokenUsage
) -> None:
    """선차감한 tpm 을 실제값으로 정산하고, 슬롯을 반납하고, 소진액을 올립니다."""
    app_state = request.app.state
    await app_state.rate_limits.finalize(
        app_state.redis,
        call.reservation,
        actual_tokens=usage.input_tokens + usage.output_tokens,
    )
    await app_state.budget_service.accumulate(
        redis=app_state.redis,
        session_factory=app_state.session_factory,
        auth=call.auth,
        outcome=call.budget,
        cost=calculate_cost(usage, call.decision.model.pricing),
    )


def record_rejection(request: Request, err: GatewayError, call: PreparedCall | None = None) -> None:
    """`outcome` 이 있는 오류만 기록합니다.

    잘못된 요청(문법·크기·미지원 필드)까지 DB 에 남기면 client 버그 하나가 테이블을 채웁니다.
    """
    if err.outcome is None:
        return
    ctx: RequestContext = request.scope["state"][STATE_REQUEST]
    auth = call.auth if call else request.scope["state"].get(STATE_AUTH)
    request.app.state.auth_events.observe(
        outcome=err.outcome.value,
        request_id=ctx.request_id,
        key_hash_prefix=err.key_hash_prefix,
        source_ip=ctx.source_ip,
        client=ctx.client,
        virtual_key_id=auth.virtual_key_id if auth else None,
        team_id=auth.team_id if auth else None,
        user_id=auth.user_id if auth else None,
        model_alias=err.model_alias or (call.decision.model.alias if call else None),
    )


async def stream_with_finalize(
    frames: AsyncIterator[bytes],
    *,
    request: Request,
    call: PreparedCall,
    accumulator: StreamAccumulator,
) -> AsyncIterator[bytes]:
    """스트림이 끝나거나 끊긴 뒤 반드시 한 번 기록합니다.

    client 가 연결을 끊어도 이미 발생한 비용은 존재합니다. `finally` 로 두는 이유가 그것입니다 —
    정상 종료, 예외, client 끊김(GeneratorExit) 어느 쪽이든 같은 자리를 지납니다.
    """
    ttft_ms: int | None = None
    started = time.monotonic()
    try:
        async for frame in frames:
            if ttft_ms is None:
                ttft_ms = int((time.monotonic() - started) * 1000)
            yield frame
    finally:
        record_usage(
            request,
            call,
            status="ERROR" if accumulator.failed else "SUCCESS",
            usage=accumulator.usage,
            ttft_ms=ttft_ms,
            is_streaming=True,
            error_code="provider_error" if accumulator.failed else None,
        )
