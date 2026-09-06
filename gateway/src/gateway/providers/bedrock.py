"""Amazon Bedrock (native) adapter.

`InvokeModel` 을 씁니다. `Converse` 가 아닌 이유는 Anthropic Messages 방언이 Bedrock native
본문과 거의 1:1 이라 변환 손실이 가장 적고, `cache_control`·`thinking` 같은 모델 고유 필드가
그대로 지나가기 때문입니다. 공통 표면이 필요해지면 그때 `Converse` adapter 를 **추가**합니다.

boto3 는 동기입니다. 이벤트 루프에서 직접 호출하면 워커 전체가 멈추므로 호출과 이벤트 스트림
순회를 전용 스레드 풀에서 실행합니다(docs/05).

자격 증명은 기본 credential chain 에 위임합니다 — 운영은 IRSA, 로컬은 개발자 프로필이 같은
코드로 동작합니다. 이 파일에 자격 증명이 등장하지 않는 것이 정상입니다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import boto3
import structlog
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from gateway.config import Settings
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import (
    ContentBlock,
    ContentBlockStart,
    ContentBlockStop,
    ContentDelta,
    ImageBlock,
    MessageDelta,
    NormalizedRequest,
    ProviderResponse,
    StreamEnd,
    StreamEvent,
    StreamStart,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
)
from gateway.core.routing import BackendDecision
from gateway.providers.base import ProviderAdapter

logger = structlog.get_logger(__name__)

ANTHROPIC_BEDROCK_VERSION = "bedrock-2023-05-31"

#: AWS 오류 코드 → 내부 코드 (docs/05).
#: AccessDeniedException 을 403 으로 넘기지 않는 것이 중요합니다. 이건 client 의 권한 문제가
#: 아니라 **gateway 의 IAM 설정 문제**라, 403 으로 주면 client 가 자기 키를 의심하며 시간을 씁니다.
_ERROR_MAP: dict[str, ErrorCode] = {
    "ValidationException": ErrorCode.INVALID_REQUEST,
    "AccessDeniedException": ErrorCode.PROVIDER_ERROR,
    "ResourceNotFoundException": ErrorCode.MODEL_INACTIVE,
    "ThrottlingException": ErrorCode.RATE_LIMIT_EXCEEDED,
    "ModelTimeoutException": ErrorCode.UPSTREAM_TIMEOUT,
    "ServiceException": ErrorCode.PROVIDER_ERROR,
    "InternalServerException": ErrorCode.PROVIDER_ERROR,
    "ModelNotReadyException": ErrorCode.PROVIDER_ERROR,
}


class BedrockAdapter(ProviderAdapter):
    def __init__(self, settings: Settings, client_factory=None) -> None:
        self._settings = settings
        self._client_factory = client_factory or self._build_client
        self._clients: dict[str, Any] = {}
        # 전용 풀입니다. 기본 executor 를 쓰면 다른 블로킹 작업과 스레드를 다투게 됩니다.
        # 풀 크기가 동시 스트림 수의 상한이 됩니다.
        self._executor = ThreadPoolExecutor(
            max_workers=settings.bedrock_thread_pool_size, thread_name_prefix="bedrock"
        )

    def _build_client(self, region: str):
        return boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotoConfig(
                max_pool_connections=50,
                connect_timeout=10,
                # 스트리밍과 같은 클라이언트를 쓰므로 길게 둡니다. 짧게 잡으면 정상적인
                # 긴 스트림이 끊깁니다.
                read_timeout=self._settings.stream_timeout,
                # gateway 가 재시도를 소유합니다. botocore 기본(최대 5회)과 곱해지면
                # 장애 시 요청 폭풍이 됩니다.
                retries={
                    "total_max_attempts": self._settings.bedrock_max_attempts,
                    "mode": "standard",
                },
            ),
        )

    def _client(self, region: str):
        """리전별로 하나씩 만들어 캐시합니다.

        `model_aliases.region` 이 모델마다 다를 수 있어, 요청마다 만들면 커넥션 풀이 매번
        새로 생깁니다.
        """
        client = self._clients.get(region)
        if client is None:
            client = self._client_factory(region)
            self._clients[region] = client
        return client

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    # ── 호출 ──

    async def invoke(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> ProviderResponse:
        body = build_body(request, decision, end_user_id=end_user_id)
        client = self._client(decision.region)
        try:
            response = await self._run(
                client.invoke_model,
                modelId=decision.call_model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            raw = await self._run(response["body"].read)
        except ClientError as exc:
            raise _translate(exc, decision) from exc
        except Exception as exc:
            logger.exception("bedrock.invoke_failed", model_id=decision.call_model_id)
            raise GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed") from exc

        return parse_response(
            raw, upstream_request_id=response.get("ResponseMetadata", {}).get("RequestId")
        )

    async def invoke_stream(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> AsyncIterator[StreamEvent]:
        body = build_body(request, decision, end_user_id=end_user_id)
        client = self._client(decision.region)
        try:
            response = await self._run(
                client.invoke_model_with_response_stream,
                modelId=decision.call_model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
        except ClientError as exc:
            # 첫 이벤트를 내기 전이라 아직 HTTP 상태로 답할 수 있습니다.
            raise _translate(exc, decision) from exc
        except Exception as exc:
            logger.exception("bedrock.stream_failed", model_id=decision.call_model_id)
            raise GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed") from exc

        return self._iter_events(response["body"])

    async def _iter_events(self, stream) -> AsyncIterator[StreamEvent]:
        """botocore 의 블로킹 EventStream 을 async 이터레이터로 바꿉니다.

        `next()` 한 번 한 번이 네트워크 대기이므로 순회 전체를 executor 에 넘깁니다.
        """
        iterator = iter(stream)
        sentinel = object()

        def _next():
            try:
                return next(iterator)
            except StopIteration:
                return sentinel

        while True:
            event = await self._run(_next)
            if event is sentinel:
                return
            chunk = event.get("chunk", {}) if isinstance(event, dict) else {}
            payload = chunk.get("bytes")
            if not payload:
                continue
            translated = to_stream_event(json.loads(payload))
            if translated is not None:
                yield translated


# ── wire 변환 (adapter 인스턴스와 무관해 테스트하기 쉽게 모듈 함수로 둡니다) ──


def build_body(
    request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
) -> bytes:
    body: dict[str, Any] = {
        "anthropic_version": ANTHROPIC_BEDROCK_VERSION,
        "max_tokens": request.max_tokens,
        "messages": [m.to_wire() for m in request.messages],
        # provider 의 남용 탐지가 "같은 사람의 연속 호출"을 묶을 수 있게 하는 불투명 식별자.
        # client 가 보낸 값이 아니라 gateway 가 정한 값입니다(docs/05).
        "metadata": {"user_id": end_user_id},
    }
    if request.system:
        body["system"] = [b.to_wire() for b in request.system]
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if request.top_k is not None:
        body["top_k"] = request.top_k
    if request.stop_sequences:
        body["stop_sequences"] = request.stop_sequences
    if request.tools:
        body["tools"] = [t.to_wire() for t in request.tools]
    if request.tool_choice is not None:
        body["tool_choice"] = request.tool_choice
    if request.reasoning and request.reasoning.budget_tokens:
        body["thinking"] = {
            "type": "enabled",
            "budget_tokens": request.reasoning.budget_tokens,
        }
    return json.dumps(body, separators=(",", ":")).encode()


def parse_response(raw: bytes, *, upstream_request_id: str | None = None) -> ProviderResponse:
    data = json.loads(raw)
    return ProviderResponse(
        response_id=data.get("id", ""),
        model_id=data.get("model", ""),
        content=[_parse_block(b) for b in data.get("content", [])],
        stop_reason=data.get("stop_reason"),
        usage=parse_usage(data.get("usage") or {}),
        upstream_request_id=upstream_request_id,
    )


def parse_usage(raw: dict[str, Any]) -> TokenUsage:
    return TokenUsage(
        input_tokens=raw.get("input_tokens", 0) or 0,
        output_tokens=raw.get("output_tokens", 0) or 0,
        cache_write_tokens=raw.get("cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=raw.get("cache_read_input_tokens", 0) or 0,
    )


def _parse_block(raw: dict[str, Any]) -> ContentBlock:
    block_type = raw.get("type")
    if block_type == "tool_use":
        return ToolUseBlock(id=raw.get("id", ""), name=raw.get("name", ""), input=raw.get("input") or {})
    if block_type == "thinking":
        return ThinkingBlock(thinking=raw.get("thinking", ""), signature=raw.get("signature"))
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=raw.get("tool_use_id", ""),
            content=raw.get("content"),
            is_error=bool(raw.get("is_error", False)),
        )
    if block_type == "image":
        source = raw.get("source") or {}
        return ImageBlock(media_type=source.get("media_type", ""), data=source.get("data", ""))
    return TextBlock(text=raw.get("text", ""))


def to_stream_event(data: dict[str, Any]) -> StreamEvent | None:
    """Bedrock 이 주는 Anthropic SSE 이벤트 JSON → 내부 이벤트.

    모르는 이벤트(`ping` 등)는 None 을 돌려 조용히 버립니다. 여기서 예외를 던지면 upstream 이
    이벤트를 하나 추가하는 것만으로 스트림 전체가 죽습니다.
    """
    event_type = data.get("type")

    if event_type == "message_start":
        message = data.get("message") or {}
        return StreamStart(
            response_id=message.get("id", ""),
            model_id=message.get("model", ""),
            usage=parse_usage(message.get("usage") or {}),
        )

    if event_type == "content_block_start":
        block = data.get("content_block") or {}
        return ContentBlockStart(
            index=data.get("index", 0),
            block_type=block.get("type", "text"),
            tool_id=block.get("id"),
            tool_name=block.get("name"),
        )

    if event_type == "content_block_delta":
        delta = data.get("delta") or {}
        return ContentDelta(
            index=data.get("index", 0),
            text=delta.get("text"),
            partial_json=delta.get("partial_json"),
            thinking=delta.get("thinking"),
            signature=delta.get("signature"),
        )

    if event_type == "content_block_stop":
        return ContentBlockStop(index=data.get("index", 0))

    if event_type == "message_delta":
        return MessageDelta(
            stop_reason=(data.get("delta") or {}).get("stop_reason"),
            usage=parse_usage(data.get("usage") or {}),
        )

    if event_type == "message_stop":
        return StreamEnd(usage=TokenUsage())

    return None


def _translate(exc: ClientError, decision: BackendDecision) -> GatewayError:
    aws_code = exc.response.get("Error", {}).get("Code", "")
    code = _ERROR_MAP.get(aws_code, ErrorCode.PROVIDER_ERROR)
    # 원문은 로그에만 남깁니다. 계정 ID·ARN·내부 엔드포인트가 섞여 나옵니다.
    logger.warning(
        "bedrock.client_error",
        aws_code=aws_code,
        model_id=decision.call_model_id,
        region=decision.region,
        error=str(exc),
    )
    messages = {
        ErrorCode.INVALID_REQUEST: "The upstream model rejected the request",
        ErrorCode.MODEL_INACTIVE: f"Model '{decision.model.alias}' is not available",
        ErrorCode.RATE_LIMIT_EXCEEDED: "Upstream model is throttling requests",
        ErrorCode.UPSTREAM_TIMEOUT: "Upstream model timed out",
    }
    return GatewayError(code, messages.get(code, "Upstream model call failed"))
