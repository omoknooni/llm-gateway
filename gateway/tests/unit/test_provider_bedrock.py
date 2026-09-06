"""Bedrock adapter 의 wire 변환과 오류 매핑 (docs/05).

실제 호출은 통합 테스트의 몫입니다. 여기서는 **경계에서 무엇이 오가는지**를 고정합니다.
"""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from gateway.config import Settings
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import (
    ContentBlockStart,
    ContentDelta,
    Message,
    MessageDelta,
    NormalizedRequest,
    ReasoningSpec,
    StreamEnd,
    StreamStart,
    TextBlock,
    ToolSpec,
)
from gateway.core.routing import BackendDecision
from gateway.providers.bedrock import (
    ANTHROPIC_BEDROCK_VERSION,
    BedrockAdapter,
    build_body,
    parse_response,
    to_stream_event,
)
from tests.unit.test_model_config import make as make_model


def decision(**overrides) -> BackendDecision:
    model = make_model()
    base = {
        "model": model,
        "provider": "BEDROCK",
        "call_model_id": "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "region": "ap-northeast-2",
        "endpoint_url": None,
    }
    return BackendDecision(**{**base, **overrides})


def request(**overrides) -> NormalizedRequest:
    base = {
        "model_alias": "claude-sonnet",
        "messages": [Message(role="user", content=[TextBlock(text="hi")])],
        "max_tokens": 100,
        "stream": False,
    }
    return NormalizedRequest(**{**base, **overrides})


# ── 요청 본문 ──


def test_body_carries_the_bedrock_anthropic_version():
    body = json.loads(build_body(request(), decision(), end_user_id="u-1"))
    assert body["anthropic_version"] == ANTHROPIC_BEDROCK_VERSION


def test_metadata_user_id_is_the_gateway_value_not_the_client_value():
    """client 가 보낸 값은 신뢰할 수 없고 provider 측 귀속을 흩뜨립니다(docs/06 Q4)."""
    body = json.loads(
        build_body(request(end_user_id="whatever-client-sent"), decision(), end_user_id="u-1")
    )
    assert body["metadata"] == {"user_id": "u-1"}


def test_optional_fields_are_omitted_when_unset():
    """None 을 그대로 실으면 Bedrock 이 ValidationException 을 냅니다."""
    body = json.loads(build_body(request(), decision(), end_user_id="u-1"))
    for field in ("temperature", "top_p", "top_k", "stop_sequences", "tools", "tool_choice", "thinking"):
        assert field not in body


def test_thinking_is_built_from_the_reasoning_spec():
    body = json.loads(
        build_body(request(reasoning=ReasoningSpec(budget_tokens=2000)), decision(), end_user_id="u")
    )
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2000}


def test_tools_are_serialized_to_anthropic_wire():
    body = json.loads(
        build_body(
            request(tools=[ToolSpec(name="search", description="d", input_schema={"type": "object"})]),
            decision(),
            end_user_id="u",
        )
    )
    assert body["tools"] == [
        {"name": "search", "input_schema": {"type": "object"}, "description": "d"}
    ]


# ── 응답 ──


def test_parse_response_maps_cache_token_names():
    """provider 이름(cache_creation/cache_read)과 우리 컬럼 이름이 다릅니다."""
    raw = json.dumps(
        {
            "id": "msg_1",
            "model": "anthropic.claude",
            "content": [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 7,
            },
        }
    ).encode()
    response = parse_response(raw, upstream_request_id="req-1")
    assert (response.usage.cache_write_tokens, response.usage.cache_read_tokens) == (3, 7)
    assert response.upstream_request_id == "req-1"


def test_parse_response_handles_tool_use_blocks():
    raw = json.dumps(
        {"id": "m", "content": [{"type": "tool_use", "id": "tu", "name": "n", "input": {"a": 1}}]}
    ).encode()
    block = parse_response(raw).content[0]
    assert (block.id, block.name, block.input) == ("tu", "n", {"a": 1})


# ── 스트림 이벤트 ──


def test_stream_events_are_translated():
    start = to_stream_event(
        {"type": "message_start", "message": {"id": "m", "model": "x", "usage": {"input_tokens": 4}}}
    )
    assert isinstance(start, StreamStart) and start.usage.input_tokens == 4

    block = to_stream_event(
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "t", "name": "n"},
        }
    )
    assert isinstance(block, ContentBlockStart) and block.tool_name == "n"

    delta = to_stream_event(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "a"}}
    )
    assert isinstance(delta, ContentDelta) and delta.text == "a"

    message_delta = to_stream_event(
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}}
    )
    assert isinstance(message_delta, MessageDelta) and message_delta.usage.output_tokens == 9

    assert isinstance(to_stream_event({"type": "message_stop"}), StreamEnd)


def test_unknown_stream_events_are_dropped_not_raised():
    """upstream 이 이벤트를 하나 추가하는 것만으로 스트림 전체가 죽으면 안 됩니다."""
    assert to_stream_event({"type": "ping"}) is None
    assert to_stream_event({"type": "something_new_in_2027"}) is None


# ── 오류 매핑 ──


def _client_error(code: str) -> ClientError:
    detail = {"Error": {"Code": code, "Message": "detail with arn:aws:iam::123456789012"}}
    return ClientError(detail, "InvokeModel")


@pytest.mark.parametrize(
    ("aws_code", "expected"),
    [
        ("ValidationException", ErrorCode.INVALID_REQUEST),
        ("AccessDeniedException", ErrorCode.PROVIDER_ERROR),
        ("ResourceNotFoundException", ErrorCode.MODEL_INACTIVE),
        ("ThrottlingException", ErrorCode.RATE_LIMIT_EXCEEDED),
        ("ModelTimeoutException", ErrorCode.UPSTREAM_TIMEOUT),
        ("InternalServerException", ErrorCode.PROVIDER_ERROR),
        ("SomethingUnheardOf", ErrorCode.PROVIDER_ERROR),
    ],
)
async def test_client_error_mapping(aws_code: str, expected: ErrorCode):
    adapter = BedrockAdapter(Settings(), client_factory=lambda region: _RaisingClient(aws_code))
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke(request(), decision(), end_user_id="u")
    assert exc.value.code is expected


async def test_access_denied_is_not_reported_as_a_client_permission_problem():
    """gateway 의 IAM 설정 문제입니다. 403 으로 주면 client 가 자기 키를 의심합니다."""
    adapter = BedrockAdapter(
        Settings(), client_factory=lambda region: _RaisingClient("AccessDeniedException")
    )
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke(request(), decision(), end_user_id="u")
    assert exc.value.status == 502


async def test_upstream_detail_is_not_leaked_to_the_client():
    """원문에는 계정 ID·ARN 이 섞여 나옵니다."""
    adapter = BedrockAdapter(Settings(), client_factory=lambda region: _RaisingClient("ValidationException"))
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke(request(), decision(), end_user_id="u")
    assert "arn:aws" not in exc.value.message


async def test_clients_are_cached_per_region():
    """요청마다 만들면 커넥션 풀이 매번 새로 생깁니다."""
    built: list[str] = []

    def factory(region: str):
        built.append(region)
        return _RaisingClient("ValidationException")

    adapter = BedrockAdapter(Settings(), client_factory=factory)
    for region in ("ap-northeast-2", "ap-northeast-2", "us-east-1"):
        with pytest.raises(GatewayError):
            await adapter.invoke(request(), decision(region=region), end_user_id="u")
    assert built == ["ap-northeast-2", "us-east-1"]


class _RaisingClient:
    def __init__(self, aws_code: str) -> None:
        self._aws_code = aws_code

    def invoke_model(self, **kwargs):
        raise _client_error(self._aws_code)

    def invoke_model_with_response_stream(self, **kwargs):
        raise _client_error(self._aws_code)
