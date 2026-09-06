"""OpenAI 호환 방언의 변환 (docs/01).

이 방언은 진짜 변환을 합니다 — 평면 문자열 ↔ 블록, tool_calls ↔ tool_use,
role="tool" ↔ tool_result. 변환이 여기 하나에만 있어야 사내 팀마다 같은 코드를 다시 쓰지 않습니다.
"""

from __future__ import annotations

import json

import pytest

from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.normalized import (
    ContentBlockStart,
    ContentDelta,
    ImageBlock,
    MessageDelta,
    ProviderResponse,
    StreamEnd,
    StreamError,
    StreamStart,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
)
from gateway.dialects.openai import OpenAIChatDialect

DIALECT = OpenAIChatDialect()


def parse(payload: dict, *, model=None):
    return DIALECT.parse(json.dumps(payload).encode(), default_max_tokens=4096, model=model)


def minimal(**overrides) -> dict:
    return {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}], **overrides}


# ── 파싱 ──


def test_system_message_moves_out_of_the_message_list():
    """OpenAI 는 system 을 messages 안에, Anthropic 은 최상위에 둡니다."""
    request = parse(
        minimal(messages=[{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}])
    )
    assert request.system == [TextBlock(text="be brief")]
    assert len(request.messages) == 1


def test_max_tokens_is_optional_and_falls_back_to_the_model_limit():
    from tests.unit.test_model_config import make as make_model

    assert parse(minimal(), model=make_model(max_output_tokens=8192)).max_tokens == 8192
    assert parse(minimal()).max_tokens == 4096  # 모델 상한도 없으면 설정 기본값


def test_max_completion_tokens_is_accepted():
    assert parse(minimal(max_completion_tokens=32)).max_tokens == 32


def test_tool_calls_become_tool_use_blocks():
    request = parse(
        minimal(
            messages=[
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":"x"}'},
                        }
                    ],
                }
            ]
        )
    )
    block = request.messages[0].content[0]
    assert isinstance(block, ToolUseBlock)
    assert (block.id, block.name, block.input) == ("call_1", "search", {"q": "x"})


def test_tool_role_becomes_a_user_tool_result():
    request = parse(
        minimal(messages=[{"role": "tool", "tool_call_id": "call_1", "content": "42"}])
    )
    message = request.messages[0]
    assert message.role == "user"
    assert message.content == [ToolResultBlock(tool_use_id="call_1", content="42")]


def test_malformed_tool_arguments_are_refused():
    with pytest.raises(GatewayError):
        parse(
            minimal(
                messages=[
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {"id": "c", "type": "function", "function": {"name": "n", "arguments": "{oops"}}
                        ],
                    }
                ]
            )
        )


def test_data_uri_images_are_accepted_and_remote_urls_are_not():
    request = parse(
        minimal(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
                    ],
                }
            ]
        )
    )
    assert request.messages[0].content[0] == ImageBlock(media_type="image/png", data="AAA")

    with pytest.raises(GatewayError) as exc:
        parse(
            minimal(
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}],
                    }
                ]
            )
        )
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("auto", {"type": "auto"}),
        ("none", {"type": "none"}),
        ("required", {"type": "any"}),
        ({"type": "function", "function": {"name": "search"}}, {"type": "tool", "name": "search"}),
    ],
)
def test_tool_choice_translation(value, expected):
    assert parse(minimal(tool_choice=value)).tool_choice == expected


def test_n_greater_than_one_is_refused():
    """비용이 배수로 늘어나는데 정책 집행 단위는 요청 하나입니다."""
    with pytest.raises(GatewayError) as exc:
        parse(minimal(n=2))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD
    assert parse(minimal(n=1)).model_alias == "gpt-x"


@pytest.mark.parametrize(
    "field", ["seed", "logit_bias", "logprobs", "presence_penalty", "frequency_penalty", "response_format"]
)
def test_documented_rejections(field: str):
    with pytest.raises(GatewayError) as exc:
        parse(minimal(**{field: 1}))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FIELD


def test_stop_accepts_string_or_list():
    assert parse(minimal(stop="END")).stop_sequences == ["END"]
    assert parse(minimal(stop=["A", "B"])).stop_sequences == ["A", "B"]


def test_user_field_is_parsed_but_marked_observation_only():
    assert parse(minimal(user="client-said")).end_user_id == "client-said"


# ── 직렬화 ──


def test_response_shape():
    response = ProviderResponse(
        response_id="msg_1",
        model_id="internal-id",
        content=[TextBlock(text="hello")],
        stop_reason="end_turn",
        usage=TokenUsage(input_tokens=10, output_tokens=3, cache_read_tokens=4),
    )
    payload = json.loads(DIALECT.response(response, model_alias="gpt-x"))
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "gpt-x"
    assert payload["choices"][0]["message"]["content"] == "hello"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
        "prompt_tokens_details": {"cached_tokens": 4},
    }


def test_tool_use_is_serialized_as_tool_calls():
    response = ProviderResponse(
        response_id="m",
        model_id="x",
        content=[ToolUseBlock(id="tu", name="search", input={"q": "x"})],
        stop_reason="tool_use",
        usage=TokenUsage(),
    )
    choice = json.loads(DIALECT.response(response, model_alias="gpt-x"))["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"] == {
        "name": "search",
        "arguments": '{"q":"x"}',
    }


def test_thinking_blocks_are_not_exposed():
    """OpenAI 스키마에 자리가 없습니다. content 에 섞으면 최종 답변으로 오해합니다."""
    response = ProviderResponse(
        response_id="m",
        model_id="x",
        content=[ThinkingBlock(thinking="secret reasoning"), TextBlock(text="answer")],
        stop_reason="end_turn",
        usage=TokenUsage(),
    )
    payload = json.loads(DIALECT.response(response, model_alias="gpt-x"))
    assert payload["choices"][0]["message"]["content"] == "answer"
    assert "secret reasoning" not in json.dumps(payload)


async def _frames(events, **kwargs) -> list[str]:
    return [f.decode() async for f in DIALECT.stream(events, model_alias="gpt-x", **kwargs)]


async def test_stream_ends_with_done_sentinel():
    async def events():
        yield StreamStart(response_id="m", model_id="x", usage=TokenUsage(input_tokens=1))
        yield ContentDelta(index=0, text="hi")
        yield MessageDelta(stop_reason="end_turn", usage=TokenUsage(output_tokens=1))
        yield StreamEnd(usage=TokenUsage(input_tokens=1, output_tokens=1))

    frames = await _frames(events())
    assert frames[-1] == "data: [DONE]\n\n"
    assert '"role":"assistant"' in frames[0]
    assert '"content":"hi"' in frames[1]
    assert '"finish_reason":"stop"' in frames[2]


async def test_usage_chunk_only_when_requested():
    async def events():
        yield StreamStart(response_id="m", model_id="x", usage=TokenUsage(input_tokens=7))
        yield StreamEnd(usage=TokenUsage(output_tokens=2))

    assert not any('"usage"' in f for f in await _frames(events()))

    with_usage = await _frames(events(), include_usage=True)
    usage_frame = next(f for f in with_usage if '"usage"' in f)
    assert '"prompt_tokens":7' in usage_frame
    # 사용량 전용 chunk 는 choices 가 비어 있습니다(OpenAI 규약).
    assert '"choices":[]' in usage_frame


async def test_streamed_tool_calls_carry_an_index():
    async def events():
        yield ContentBlockStart(index=0, block_type="tool_use", tool_id="c1", tool_name="search")
        yield ContentDelta(index=0, partial_json='{"q"')

    frames = await _frames(events())
    assert '"index":0' in frames[0] and '"name":"search"' in frames[0]
    assert '"arguments":"{\\"q\\""' in frames[1]


async def test_stream_error_is_reported_before_done():
    """조용히 끊으면 client 는 정상 종료와 구분할 수 없습니다."""

    async def events():
        yield StreamError(code="timeout_error", message="upstream stopped")

    frames = await _frames(events())
    assert any('"error"' in f and "upstream stopped" in f for f in frames)
    assert frames[-1] == "data: [DONE]\n\n"
