"""Bedrock Mantle adapter.

Bedrock native 와 다른 점은 전송 방식입니다 — boto3 가 아니라 **async httpx + Bearer** 이고,
엔드포인트는 모델 카탈로그의 `endpoint_url` 입니다. 본문은 표준 Anthropic Messages 라
`anthropic_version` 이 본문이 아니라 **헤더**로 가고 `model` 이 본문에 들어갑니다.

IAM 네임스페이스도 다릅니다(`bedrock-mantle:` — `bedrock:` 이 아닙니다). 실전에서 가장 많이
틀리는 지점이라 docs/05 에 적어 두었습니다.

전 구간 async 라 Bedrock adapter 같은 스레드 풀이 필요 없습니다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import structlog

from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import NormalizedRequest, ProviderResponse, StreamEvent
from gateway.core.routing import BackendDecision
from gateway.providers.base import ProviderAdapter
from gateway.providers.bedrock import build_body, parse_response, to_stream_event
from gateway.providers.credentials import MantleCredentialBroker

logger = structlog.get_logger(__name__)

ANTHROPIC_VERSION = "2023-06-01"

#: HTTP 상태 → 내부 코드. Bedrock native 의 오류 코드 매핑과 같은 판단을 따릅니다.
_STATUS_MAP: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.PROVIDER_ERROR,  # 우리 토큰 문제입니다. client 키 문제가 아닙니다.
    403: ErrorCode.PROVIDER_ERROR,  # IAM 설정 문제입니다.
    404: ErrorCode.MODEL_INACTIVE,
    413: ErrorCode.REQUEST_TOO_LARGE,
    429: ErrorCode.RATE_LIMIT_EXCEEDED,
    504: ErrorCode.UPSTREAM_TIMEOUT,
}


class MantleAdapter(ProviderAdapter):
    def __init__(self, http_client: httpx.AsyncClient, broker: MantleCredentialBroker) -> None:
        self._http = http_client
        self._broker = broker

    async def _headers(self, region: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {await self._broker.bearer_token(region)}",
            # Bedrock native 는 본문에, Mantle 은 헤더에 둡니다. 이 차이를 adapter 가 흡수합니다.
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _url(self, decision: BackendDecision) -> str:
        if not decision.endpoint_url:
            # 모델 해석에서 이미 걸러지지만, adapter 가 자기 전제를 다시 확인합니다.
            raise GatewayError(ErrorCode.PROVIDER_ERROR, "Mantle endpoint is not configured")
        return f"{decision.endpoint_url.rstrip('/')}/v1/messages"

    def _body(self, request: NormalizedRequest, decision: BackendDecision, end_user_id: str) -> bytes:
        data = json.loads(build_body(request, decision, end_user_id=end_user_id))
        # anthropic_version 은 헤더로 가고, model 은 본문에 들어갑니다.
        data.pop("anthropic_version", None)
        data["model"] = decision.call_model_id
        return json.dumps(data, separators=(",", ":")).encode()

    async def invoke(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> ProviderResponse:
        url = self._url(decision)
        try:
            response = await self._http.post(
                url, content=self._body(request, decision, end_user_id),
                headers=await self._headers(decision.region),
            )
        except Exception as exc:
            logger.exception("mantle.invoke_failed", model_id=decision.call_model_id)
            raise GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed") from exc

        if response.status_code != 200:
            raise _translate(response.status_code, response.content, decision)
        return parse_response(response.content)

    async def invoke_stream(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> AsyncIterator[StreamEvent]:
        url = self._url(decision)
        body = self._body(request, decision, end_user_id)
        headers = await self._headers(decision.region)

        # 스트림을 열고 **상태 코드를 먼저 읽습니다.** 열어보지도 않고 성공을 반환하면
        # non-200 이 "200 + 본문 속 에러"로 둔갑해 client 가 실패를 성공으로 처리합니다.
        context = self._http.stream("POST", url, content=body, headers=headers)
        try:
            response = await context.__aenter__()
        except Exception as exc:
            logger.exception("mantle.stream_connect_failed", model_id=decision.call_model_id)
            raise GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed") from exc

        if response.status_code != 200:
            detail = b""
            try:
                detail = await response.aread()
            finally:
                await context.__aexit__(None, None, None)
            raise _translate(response.status_code, detail, decision)

        return _events(context, response)


async def _events(context, response) -> AsyncIterator[StreamEvent]:
    try:
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload or payload == "[DONE]":
                continue
            event = to_stream_event(json.loads(payload))
            if event is not None:
                yield event
    finally:
        # 컨텍스트를 닫지 않으면 커넥션이 풀로 돌아가지 않습니다.
        await context.__aexit__(None, None, None)


def _translate(status: int, detail: bytes, decision: BackendDecision) -> GatewayError:
    code = _STATUS_MAP.get(status, ErrorCode.PROVIDER_ERROR)
    logger.warning(
        "mantle.http_error",
        status=status,
        model_id=decision.call_model_id,
        region=decision.region,
        # 본문에는 계정 정보가 섞여 나올 수 있어 앞부분만, 로그에만 남깁니다.
        detail=detail[:500].decode("utf-8", "replace"),
    )
    messages = {
        ErrorCode.INVALID_REQUEST: "The upstream model rejected the request",
        ErrorCode.MODEL_INACTIVE: f"Model '{decision.model.alias}' is not available",
        ErrorCode.RATE_LIMIT_EXCEEDED: "Upstream model is throttling requests",
        ErrorCode.UPSTREAM_TIMEOUT: "Upstream model timed out",
        ErrorCode.REQUEST_TOO_LARGE: "Request body is too large",
    }
    return GatewayError(code, messages.get(code, "Upstream model call failed"))
