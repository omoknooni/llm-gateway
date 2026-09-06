"""Anthropic Messages 방언 (`/v1/messages`).

내부 표현이 Anthropic 계열 모양이라 이 방언의 변환은 거의 항등에 가깝습니다. 그래도 파싱을
거치는 이유는 **미지원 필드를 거절하기 위해서**입니다 — 통과시키면 provider 가 무엇을 받는지
우리가 모르게 됩니다(docs/01).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from gateway.core.dialect import ApiDialect
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.model import ModelConfig
from gateway.core.normalized import (
    ContentBlock,
    ContentBlockStart,
    ContentBlockStop,
    ContentDelta,
    ImageBlock,
    Message,
    MessageDelta,
    NormalizedRequest,
    ProviderResponse,
    ReasoningSpec,
    StreamEnd,
    StreamError,
    StreamEvent,
    StreamStart,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from gateway.dialects.base import (
    load_json,
    reject_unknown_fields,
    require,
    resolve_max_tokens,
    sse,
)

#: docs/01 의 allow-list. 이 집합과 문서를 함께 갱신합니다.
ACCEPTED_FIELDS = frozenset(
    {
        "model",
        "messages",
        "system",
        "max_tokens",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "tools",
        "tool_choice",
        "thinking",
        "metadata",
        # 본문에 실려 오면 무시하고 헤더 값을 씁니다. 거절 대상은 아닙니다.
        "anthropic_version",
    }
)

_TOOL_CHOICE_TYPES = frozenset({"auto", "any", "tool", "none"})


class AnthropicMessagesDialect:
    dialect = ApiDialect.ANTHROPIC_MESSAGES

    # ── 파싱 ──

    def parse(
        self, body: bytes, *, default_max_tokens: int, model: ModelConfig | None = None
    ) -> NormalizedRequest:
        return self.parse_data(load_json(body), default_max_tokens=default_max_tokens, model=model)

    def parse_data(
        self, data: dict[str, Any], *, default_max_tokens: int, model: ModelConfig | None = None
    ) -> NormalizedRequest:
        """이미 읽어 둔 JSON 에서 파싱합니다.

        라우터는 모델을 해석하려고 본문을 한 번 읽어야 하고, `max_tokens` 검증에는 그 모델이
        필요합니다. 같은 본문을 두 번 파싱하지 않기 위한 진입점입니다.
        """
        reject_unknown_fields(data, ACCEPTED_FIELDS)

        model_alias = require(data, "model")
        if not isinstance(model_alias, str):
            raise GatewayError(ErrorCode.INVALID_REQUEST, "'model' must be a string", param="model")

        # Anthropic 스펙상 max_tokens 는 필수입니다. 기본값으로 채우면 스펙을 어기는 client 를
        # 우리가 덮어 주는 셈이라, 그 client 는 다른 게이트웨이에서 깨집니다.
        max_tokens = resolve_max_tokens(require(data, "max_tokens"), model, default_max_tokens)

        return NormalizedRequest(
            model_alias=model_alias,
            messages=[_parse_message(m) for m in require(data, "messages")],
            max_tokens=max_tokens,
            stream=bool(data.get("stream", False)),
            system=_parse_system(data.get("system")),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            top_k=data.get("top_k"),
            stop_sequences=list(data.get("stop_sequences") or []),
            tools=[_parse_tool(t) for t in data.get("tools") or []],
            tool_choice=_parse_tool_choice(data.get("tool_choice")),
            reasoning=_parse_thinking(data.get("thinking")),
            end_user_id=_parse_metadata(data.get("metadata")),
        )

    # ── 직렬화 ──

    def response(self, response: ProviderResponse, *, model_alias: str) -> bytes:
        import json

        payload = {
            "id": response.response_id,
            "type": "message",
            "role": "assistant",
            # client 가 요청한 alias 를 돌려줍니다. provider 의 내부 모델 id 를 노출하지 않습니다.
            "model": model_alias,
            "content": [b.to_wire() for b in response.content],
            "stop_reason": response.stop_reason,
            "stop_sequence": None,
            "usage": _usage_wire(response.usage),
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    async def stream(
        self, events: AsyncIterator[StreamEvent], *, model_alias: str
    ) -> AsyncIterator[bytes]:
        """내부 이벤트를 Anthropic SSE 로 옮깁니다.

        이벤트 종류와 순서가 스펙이라 client SDK 가 그대로 기대합니다.
        """
        async for event in events:
            match event:
                case StreamStart():
                    yield sse(
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "id": event.response_id,
                                "type": "message",
                                "role": "assistant",
                                "model": model_alias,
                                "content": [],
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": _usage_wire(event.usage),
                            },
                        },
                    )
                case ContentBlockStart():
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": event.index,
                            "content_block": _empty_block_wire(event),
                        },
                    )
                case ContentDelta():
                    yield sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": event.index,
                            "delta": _delta_wire(event),
                        },
                    )
                case ContentBlockStop():
                    yield sse(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": event.index},
                    )
                case MessageDelta():
                    yield sse(
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {
                                "stop_reason": event.stop_reason,
                                "stop_sequence": None,
                            },
                            "usage": {"output_tokens": event.usage.output_tokens},
                        },
                    )
                case StreamEnd():
                    yield sse("message_stop", {"type": "message_stop"})
                case StreamError():
                    # 200 헤더가 이미 나간 뒤라 HTTP 상태로는 말할 수 없습니다.
                    yield sse(
                        "error",
                        {"type": "error", "error": {"type": event.code, "message": event.message}},
                    )


# ── 파싱 헬퍼 ──


def _parse_message(raw: Any) -> Message:
    if not isinstance(raw, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Each message must be an object")
    role = raw.get("role")
    if role not in ("user", "assistant"):
        raise GatewayError(
            ErrorCode.INVALID_REQUEST, f"Unsupported message role: {role!r}", param="messages"
        )
    return Message(role=role, content=_parse_content(raw.get("content")))


def _parse_system(raw: Any) -> list[ContentBlock] | None:
    if raw is None:
        return None
    return _parse_content(raw)


def _parse_content(raw: Any) -> list[ContentBlock]:
    #: 문자열 축약형은 스펙의 일부입니다. 한 개짜리 text 블록과 같습니다.
    if isinstance(raw, str):
        return [TextBlock(text=raw)]
    if not isinstance(raw, list):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "'content' must be a string or a list")
    return [_parse_block(b) for b in raw]


def _parse_block(raw: Any) -> ContentBlock:
    if not isinstance(raw, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Each content block must be an object")

    block_type = raw.get("type")
    cache_hint = "cache_control" in raw

    if block_type == "text":
        return TextBlock(text=raw.get("text", ""), cache_hint=cache_hint)

    if block_type == "image":
        source = raw.get("source") or {}
        if source.get("type") != "base64":
            # Bedrock 은 URL 소스를 받지 않습니다. 통과시키면 provider 오류로 나타나
            # client 는 우리 문제인지 자기 문제인지 알 수 없습니다.
            raise GatewayError(
                ErrorCode.UNSUPPORTED_FIELD,
                "Only base64 image sources are supported",
                param="source.type",
            )
        return ImageBlock(media_type=source.get("media_type", ""), data=source.get("data", ""))

    if block_type == "tool_use":
        return ToolUseBlock(
            id=raw.get("id", ""), name=raw.get("name", ""), input=raw.get("input") or {}
        )

    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=raw.get("tool_use_id", ""),
            content=raw.get("content"),
            is_error=bool(raw.get("is_error", False)),
        )

    if block_type == "thinking":
        return ThinkingBlock(thinking=raw.get("thinking", ""), signature=raw.get("signature"))

    raise GatewayError(
        ErrorCode.UNSUPPORTED_FIELD,
        f"Unsupported content block type: {block_type!r}",
        param="content.type",
    )


def _parse_tool(raw: Any) -> ToolSpec:
    if not isinstance(raw, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Each tool must be an object", param="tools")
    name = raw.get("name")
    if not name:
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Tool 'name' is required", param="tools")
    return ToolSpec(
        name=name,
        description=raw.get("description"),
        input_schema=raw.get("input_schema") or {},
    )


def _parse_tool_choice(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("type") not in _TOOL_CHOICE_TYPES:
        raise GatewayError(
            ErrorCode.INVALID_REQUEST, "Unsupported 'tool_choice'", param="tool_choice"
        )
    return raw


def _parse_thinking(raw: Any) -> ReasoningSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "'thinking' must be an object", param="thinking")
    if raw.get("type") == "disabled":
        return None
    return ReasoningSpec(budget_tokens=raw.get("budget_tokens"))


def _parse_metadata(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "'metadata' must be an object", param="metadata")
    reject_unknown_fields(raw, {"user_id"})
    return raw.get("user_id")


# ── 직렬화 헬퍼 ──


def _usage_wire(usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": usage.cache_write_tokens,
        "cache_read_input_tokens": usage.cache_read_tokens,
    }


def _empty_block_wire(event: ContentBlockStart) -> dict[str, Any]:
    if event.block_type == "tool_use":
        return {"type": "tool_use", "id": event.tool_id, "name": event.tool_name, "input": {}}
    if event.block_type == "thinking":
        return {"type": "thinking", "thinking": ""}
    return {"type": "text", "text": ""}


def _delta_wire(event: ContentDelta) -> dict[str, Any]:
    if event.partial_json is not None:
        return {"type": "input_json_delta", "partial_json": event.partial_json}
    if event.thinking is not None:
        return {"type": "thinking_delta", "thinking": event.thinking}
    if event.signature is not None:
        return {"type": "signature_delta", "signature": event.signature}
    return {"type": "text_delta", "text": event.text or ""}


def new_message_id() -> str:
    """provider 가 id 를 주지 않는 경우의 대체값."""
    return f"msg_{uuid.uuid4().hex}"
