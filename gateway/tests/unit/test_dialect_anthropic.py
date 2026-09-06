"""Anthropic Messages 방언의 파싱과 직렬화 (docs/01)."""

from __future__ import annotations

import json

import pytest

from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import (
    ContentBlockStart,
    ContentBlockStop,
    ContentDelta,
    MessageDelta,
    ProviderResponse,
    StreamEnd,
    StreamError,
    StreamStart,
    TextBlock,
    TokenUsage,
    ToolUseBlock,
)
from gateway.dialects.anthropic import AnthropicMessagesDialect
from tests.unit.test_model_config import make as make_model

DIALECT = AnthropicMessagesDialect()


def parse(payload: dict, *, model=None):
    return DIALECT.parse(json.dumps(payload).encode(), default_max_tokens=4096, model=model)


def minimal(**overrides) -> dict:
    return {"model": "claude-sonnet", "max_tokens": 100,
            "messages": [{"role": "user", "content": "hi"}], **overrides}


# ── 파싱 ──


def test_string_content_is_a_single_text_block():
    request = parse(minimal())
    assert request.messages[0].content == [TextBlock(text="hi")]


def test_cache_control_becomes_a_hint():
    request = parse(
        minimal(
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
                }
            ]
        )
    )
    assert request.messages[0].content[0].cache_hint is True


def test_unknown_top_level_field_is_rejected_with_its_name():
    with pytest.raises(GatewayError) as exc:
        parse(minimal(seed=42))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD
    assert "'seed'" in exc.value.message


@pytest.mark.parametrize("field", ["service_tier", "container", "mcp_servers"])
def test_documented_rejections(field: str):
    with pytest.raises(GatewayError) as exc:
        parse(minimal(**{field: "x"}))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD


def test_max_tokens_is_required_by_the_spec():
    """기본값으로 채워 주면 그 client 는 다른 게이트웨이에서 깨집니다."""
    payload = minimal()
    del payload["max_tokens"]
    with pytest.raises(GatewayError) as exc:
        parse(payload)
    assert exc.value.code is ErrorCode.INVALID_REQUEST


def test_max_tokens_over_the_model_limit_is_refused_not_clamped():
    """잘라 보내면 client 는 응답이 짧은 이유를 모델 탓으로 돌립니다."""
    with pytest.raises(GatewayError) as exc:
        parse(minimal(max_tokens=999_999), model=make_model(max_output_tokens=8192))
    assert "exceeds the limit" in exc.value.message


def test_url_image_source_is_refused():
    with pytest.raises(GatewayError) as exc:
        parse(
            minimal(
                messages=[
                    {"role": "user", "content": [{"type": "image", "source": {"type": "url"}}]}
                ]
            )
        )
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD


def test_unknown_block_type_is_refused():
    with pytest.raises(GatewayError):
        parse(minimal(messages=[{"role": "user", "content": [{"type": "video"}]}]))


def test_unknown_role_is_refused():
    with pytest.raises(GatewayError):
        parse(minimal(messages=[{"role": "system", "content": "x"}]))


def test_metadata_accepts_only_user_id():
    assert parse(minimal(metadata={"user_id": "u-1"})).end_user_id == "u-1"
    with pytest.raises(GatewayError):
        parse(minimal(metadata={"user_id": "u-1", "session": "s"}))


def test_thinking_disabled_is_not_reasoning():
    assert parse(minimal(thinking={"type": "disabled"})).reasoning is None
    assert parse(minimal(thinking={"type": "enabled", "budget_tokens": 2000})).reasoning.budget_tokens == 2000


def test_invalid_json_is_a_bad_request():
    with pytest.raises(GatewayError) as exc:
        DIALECT.parse(b"{ not json", default_max_tokens=4096)
    assert exc.value.code is ErrorCode.INVALID_REQUEST


# ── 직렬화 ──


def test_response_reports_the_requested_alias_not_the_provider_model_id():
    """client 에게 내부 모델 id 를 노출하지 않습니다."""
    response = ProviderResponse(
        response_id="msg_1",
        model_id="apac.anthropic.claude-sonnet-4-5-v1:0",
        content=[TextBlock(text="hello")],
        stop_reason="end_turn",
        usage=TokenUsage(input_tokens=10, output_tokens=3, cache_read_tokens=7),
    )
    payload = json.loads(DIALECT.response(response, model_alias="claude-sonnet"))
    assert payload["model"] == "claude-sonnet"
    assert payload["content"] == [{"type": "text", "text": "hello"}]
    assert payload["usage"]["cache_read_input_tokens"] == 7


async def test_stream_frames_follow_the_spec_order():
    async def events():
        yield StreamStart(response_id="msg_1", model_id="m", usage=TokenUsage(input_tokens=5))
        yield ContentBlockStart(index=0, block_type="text")
        yield ContentDelta(index=0, text="he")
        yield ContentBlockStop(index=0)
        yield MessageDelta(stop_reason="end_turn", usage=TokenUsage(output_tokens=2))
        yield StreamEnd(usage=TokenUsage(input_tokens=5, output_tokens=2))

    frames = [f.decode() async for f in DIALECT.stream(events(), model_alias="claude-sonnet")]
    names = [f.split("\n", 1)[0].removeprefix("event: ") for f in frames]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert '"model":"claude-sonnet"' in frames[0]


async def test_tool_use_stream_uses_input_json_delta():
    async def events():
        yield ContentBlockStart(index=1, block_type="tool_use", tool_id="tu_1", tool_name="search")
        yield ContentDelta(index=1, partial_json='{"q":')

    frames = [f.decode() async for f in DIALECT.stream(events(), model_alias="a")]
    assert '"name":"search"' in frames[0]
    assert '"type":"input_json_delta"' in frames[1]


async def test_stream_error_is_a_frame_not_a_status():
    """200 헤더가 이미 나간 뒤라 HTTP 상태로는 말할 수 없습니다."""

    async def events():
        yield StreamError(code="overloaded_error", message="upstream is busy")

    frames = [f.decode() async for f in DIALECT.stream(events(), model_alias="a")]
    assert frames[0].startswith("event: error")
    assert "upstream is busy" in frames[0]


def test_tool_use_block_round_trips_to_wire():
    block = ToolUseBlock(id="tu_1", name="search", input={"q": "x"})
    assert block.to_wire() == {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "x"}}
