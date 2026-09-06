"""OpenAI 호환 방언 (`/v1/chat/completions`).

두 방언은 **동등한 시민**입니다. 한쪽을 다른 쪽으로 변환해 내보내는 종속 관계를 만들지 않습니다
(ADR-0003). 다만 내부 표현이 블록 기반이라, 이 방언은 진짜 변환을 합니다 —
평면 문자열 ↔ 블록, `tool_calls` ↔ `tool_use`, `role="tool"` ↔ `tool_result`.

변환이 이 파일 하나에만 있으므로, 사내 팀마다 같은 변환 코드를 다시 쓰지 않습니다.
"""

from __future__ import annotations

import json
import time
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
    TokenUsage,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from gateway.dialects.base import (
    load_json,
    reject_unknown_fields,
    require,
    resolve_max_tokens,
)

#: docs/01 의 allow-list. 이 집합과 문서를 함께 갱신합니다.
ACCEPTED_FIELDS = frozenset(
    {
        "model",
        "messages",
        "max_tokens",
        "max_completion_tokens",
        "stream",
        "stream_options",
        "temperature",
        "top_p",
        "stop",
        "tools",
        "tool_choice",
        "user",
        "reasoning_effort",
        # n 은 1 만 허용합니다. 값 검사가 필요해 allow-list 에는 넣고 아래에서 거절합니다.
        "n",
    }
)

#: 내부 stop_reason → OpenAI finish_reason.
_FINISH_REASON = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


class OpenAIChatDialect:
    dialect = ApiDialect.OPENAI_CHAT

    # ── 파싱 ──

    def parse(
        self, body: bytes, *, default_max_tokens: int, model: ModelConfig | None = None
    ) -> NormalizedRequest:
        return self.parse_data(load_json(body), default_max_tokens=default_max_tokens, model=model)

    def parse_data(
        self, data: dict[str, Any], *, default_max_tokens: int, model: ModelConfig | None = None
    ) -> NormalizedRequest:
        reject_unknown_fields(data, ACCEPTED_FIELDS)

        if data.get("n") not in (None, 1):
            # 비용이 배수로 늘어나는데 정책 집행 단위는 요청 하나입니다.
            raise GatewayError(
                ErrorCode.UNSUPPORTED_FIELD, "Only n=1 is supported", param="n"
            )

        model_alias = require(data, "model")
        requested_max = data.get("max_completion_tokens") or data.get("max_tokens")
        # Anthropic 과 달리 OpenAI 는 max_tokens 가 선택입니다. 모델 상한으로 채웁니다.
        max_tokens = resolve_max_tokens(requested_max, model, default_max_tokens)

        system, messages = _split_messages(require(data, "messages"))

        return NormalizedRequest(
            model_alias=model_alias,
            messages=messages,
            max_tokens=max_tokens,
            stream=bool(data.get("stream", False)),
            system=system or None,
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
            stop_sequences=_parse_stop(data.get("stop")),
            tools=[_parse_tool(t) for t in data.get("tools") or []],
            tool_choice=_parse_tool_choice(data.get("tool_choice")),
            reasoning=(
                ReasoningSpec(effort=data["reasoning_effort"])
                if data.get("reasoning_effort")
                else None
            ),
            end_user_id=data.get("user"),
        )

    # ── 직렬화 ──

    def response(self, response: ProviderResponse, *, model_alias: str) -> bytes:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in response.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input, separators=(",", ":")),
                        },
                    }
                )
            # thinking 블록은 내보내지 않습니다. OpenAI 스키마에 대응 자리가 없고,
            # content 에 섞으면 client 가 모델의 최종 답변으로 오해합니다.

        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls

        payload = {
            "id": _completion_id(response.response_id),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_alias,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": _FINISH_REASON.get(response.stop_reason or "", "stop"),
                }
            ],
            "usage": _usage_wire(response.usage),
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    async def stream(
        self, events: AsyncIterator[StreamEvent], *, model_alias: str, include_usage: bool = False
    ) -> AsyncIterator[bytes]:
        """내부 이벤트를 chat.completion.chunk 로 옮깁니다.

        블록 인덱스 기반 이벤트에서 평면 delta 를 만드는 방향입니다. 반대 방향(평면 → 블록)은
        손실이 생기므로, 내부 표현이 블록 쪽인 이유이기도 합니다.
        """
        completion_id = _completion_id(None)
        created = int(time.time())
        usage = TokenUsage()
        #: content block index → tool_calls 배열의 index. 텍스트 블록은 여기 들어오지 않습니다.
        tool_slots: dict[int, int] = {}
        started = False

        def chunk(delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
            return _data(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_alias,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                }
            )

        async for event in events:
            match event:
                case StreamStart():
                    usage.merge(event.usage)
                    started = True
                    yield chunk({"role": "assistant", "content": ""})
                case ContentBlockStart():
                    if event.block_type == "tool_use":
                        slot = len(tool_slots)
                        tool_slots[event.index] = slot
                        yield chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": slot,
                                        "id": event.tool_id,
                                        "type": "function",
                                        "function": {"name": event.tool_name, "arguments": ""},
                                    }
                                ]
                            }
                        )
                case ContentDelta():
                    if event.partial_json is not None and event.index in tool_slots:
                        yield chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": tool_slots[event.index],
                                        "function": {"arguments": event.partial_json},
                                    }
                                ]
                            }
                        )
                    elif event.text:
                        yield chunk({"content": event.text})
                    # thinking delta 는 내보내지 않습니다(대응 자리가 없습니다).
                case ContentBlockStop():
                    pass
                case MessageDelta():
                    usage.merge(event.usage)
                    yield chunk({}, _FINISH_REASON.get(event.stop_reason or "", "stop"))
                case StreamEnd():
                    usage.merge(event.usage)
                    if include_usage:
                        # 사용량 전용 chunk 는 choices 가 비어 있습니다(OpenAI 규약).
                        yield _data(
                            {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model_alias,
                                "choices": [],
                                "usage": _usage_wire(usage),
                            }
                        )
                    yield b"data: [DONE]\n\n"
                case StreamError():
                    # OpenAI 스펙에는 스트림 오류 프레임이 없습니다. 실무 관례를 따라 error 를
                    # 실은 data 프레임을 보내고 종료합니다 — 조용히 끊으면 client 는 정상 종료와
                    # 구분할 수 없습니다.
                    if not started:
                        yield chunk({"role": "assistant", "content": ""})
                    yield _data({"error": {"message": event.message, "type": event.code}})
                    yield b"data: [DONE]\n\n"


# ── 파싱 헬퍼 ──


def _split_messages(raw: Any) -> tuple[list[ContentBlock], list[Message]]:
    """system 메시지를 messages 배열에서 분리합니다.

    OpenAI 는 system 을 messages 안에 두고 Anthropic 은 최상위 필드로 둡니다. 내부 표현은
    후자를 따르므로 여기서 갈라냅니다.
    """
    if not isinstance(raw, list):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "'messages' must be a list", param="messages")

    system: list[ContentBlock] = []
    messages: list[Message] = []
    for item in raw:
        if not isinstance(item, dict):
            raise GatewayError(ErrorCode.INVALID_REQUEST, "Each message must be an object")
        role = item.get("role")

        if role in ("system", "developer"):
            system.extend(_parse_parts(item.get("content")))
        elif role == "tool":
            # tool 결과는 Anthropic 에서 user 턴의 tool_result 블록입니다.
            messages.append(
                Message(
                    role="user",
                    content=[
                        ToolResultBlock(
                            tool_use_id=item.get("tool_call_id", ""),
                            content=item.get("content"),
                        )
                    ],
                )
            )
        elif role in ("user", "assistant"):
            blocks = _parse_parts(item.get("content"))
            blocks.extend(_parse_tool_calls(item.get("tool_calls")))
            messages.append(Message(role=role, content=blocks))
        else:
            raise GatewayError(
                ErrorCode.INVALID_REQUEST, f"Unsupported message role: {role!r}", param="messages"
            )

    return system, messages


def _parse_parts(content: Any) -> list[ContentBlock]:
    if content is None:
        return []
    if isinstance(content, str):
        return [TextBlock(text=content)]
    if not isinstance(content, list):
        raise GatewayError(ErrorCode.INVALID_REQUEST, "'content' must be a string or a list")

    blocks: list[ContentBlock] = []
    for part in content:
        if not isinstance(part, dict):
            raise GatewayError(ErrorCode.INVALID_REQUEST, "Each content part must be an object")
        part_type = part.get("type")
        if part_type == "text":
            blocks.append(TextBlock(text=part.get("text", "")))
        elif part_type == "image_url":
            blocks.append(_parse_image_url(part.get("image_url") or {}))
        else:
            raise GatewayError(
                ErrorCode.UNSUPPORTED_FIELD,
                f"Unsupported content part type: {part_type!r}",
                param="content.type",
            )
    return blocks


def _parse_image_url(image_url: dict[str, Any]) -> ImageBlock:
    """data URI 만 받습니다.

    Bedrock 은 원격 URL 이미지를 받지 않습니다. 통과시키면 provider 오류로 나타나 client 는
    우리 문제인지 자기 문제인지 알 수 없습니다.
    """
    url = image_url.get("url", "")
    if not url.startswith("data:"):
        raise GatewayError(
            ErrorCode.UNSUPPORTED_FIELD,
            "Only base64 data URIs are supported for images",
            param="image_url.url",
        )
    header, _, data = url.partition(",")
    media_type = header.removeprefix("data:").split(";")[0]
    return ImageBlock(media_type=media_type, data=data)


def _parse_tool_calls(raw: Any) -> list[ContentBlock]:
    if not raw:
        return []
    blocks: list[ContentBlock] = []
    for call in raw:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError as exc:
            raise GatewayError(
                ErrorCode.INVALID_REQUEST,
                "tool_calls[].function.arguments is not valid JSON",
                param="tool_calls",
            ) from exc
        blocks.append(
            ToolUseBlock(id=call.get("id", ""), name=function.get("name", ""), input=parsed)
        )
    return blocks


def _parse_stop(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(s) for s in raw]
    raise GatewayError(ErrorCode.INVALID_REQUEST, "'stop' must be a string or a list", param="stop")


def _parse_tool(raw: Any) -> ToolSpec:
    if not isinstance(raw, dict) or raw.get("type") != "function":
        raise GatewayError(
            ErrorCode.UNSUPPORTED_FIELD, "Only function tools are supported", param="tools"
        )
    function = raw.get("function") or {}
    name = function.get("name")
    if not name:
        raise GatewayError(ErrorCode.INVALID_REQUEST, "Tool 'name' is required", param="tools")
    return ToolSpec(
        name=name,
        description=function.get("description"),
        input_schema=function.get("parameters") or {"type": "object", "properties": {}},
    )


def _parse_tool_choice(raw: Any) -> dict[str, Any] | None:
    """OpenAI 의 표현을 내부(=Anthropic) 표현으로 옮깁니다."""
    if raw is None:
        return None
    if raw == "auto":
        return {"type": "auto"}
    if raw == "none":
        return {"type": "none"}
    if raw == "required":
        return {"type": "any"}
    if isinstance(raw, dict) and raw.get("type") == "function":
        name = (raw.get("function") or {}).get("name")
        if name:
            return {"type": "tool", "name": name}
    raise GatewayError(
        ErrorCode.INVALID_REQUEST, "Unsupported 'tool_choice'", param="tool_choice"
    )


# ── 직렬화 헬퍼 ──


def _usage_wire(usage: TokenUsage) -> dict[str, Any]:
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
        # 캐시 토큰은 OpenAI 스키마의 details 자리에 실립니다. 총합에 다시 더하지 않습니다.
        "prompt_tokens_details": {"cached_tokens": usage.cache_read_tokens},
    }


def _data(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _completion_id(response_id: str | None) -> str:
    if response_id and response_id.startswith("chatcmpl-"):
        return response_id
    return f"chatcmpl-{uuid.uuid4().hex}"

