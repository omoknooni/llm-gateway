"""사용량 기록과 비용 계산 (docs/README 의 usage 계약)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gateway.core.model import ModelPricing
from gateway.core.normalized import TokenUsage
from gateway.services.usage_recorder import UsageRecord, UsageRecorder, calculate_cost

PRICING = ModelPricing(
    input_per_1k=Decimal("0.00300000"),
    output_per_1k=Decimal("0.01500000"),
    cache_write_per_1k=Decimal("0.00375000"),
    cache_read_per_1k=Decimal("0.00030000"),
)


def test_cost_uses_all_four_token_kinds():
    usage = TokenUsage(
        input_tokens=1000, output_tokens=1000, cache_write_tokens=1000, cache_read_tokens=1000
    )
    assert calculate_cost(usage, PRICING) == Decimal("0.022050")


def test_cost_is_decimal_all_the_way():
    """float 를 거치면 단가의 유효숫자가 조용히 깎입니다."""
    cost = calculate_cost(TokenUsage(input_tokens=1), PRICING)
    assert isinstance(cost, Decimal)
    assert cost == Decimal("0.000003")


def test_cost_is_quantized_to_the_column_scale():
    """estimated_cost_usd 는 numeric(14,6) 입니다."""
    cost = calculate_cost(TokenUsage(input_tokens=1, output_tokens=1), PRICING)
    assert cost.as_tuple().exponent == -6


def test_missing_pricing_is_zero_not_a_failure():
    """호출은 이미 일어났습니다. 기록은 남기고 0 원 집계는 따로 드러냅니다."""
    assert calculate_cost(TokenUsage(input_tokens=10_000), None) == Decimal("0")


def _record(request_id: str) -> UsageRecord:
    from gateway.core.clock import utcnow

    return UsageRecord(
        request_id=request_id,
        occurred_at=utcnow(),
        team_id="t",
        user_id="u",
        virtual_key_id="vk",
        model_alias="claude-sonnet",
        provider_model_id="apac.anthropic.x",
        dialect="ANTHROPIC_MESSAGES",
        status="SUCCESS",
        usage=TokenUsage(input_tokens=1),
        latency_ms=10,
        ttft_ms=None,
        is_streaming=False,
        estimated_cost_usd=Decimal("0"),
        pricing_id=None,
        error_code=None,
        client="claude-code",
    )


async def test_records_are_spooled_when_the_database_is_gone():
    recorder = UsageRecorder(spool_max=10)
    await recorder.record(None, _record("r1"))
    assert recorder.spool_size == 1


async def test_spool_overflow_is_counted_not_silent():
    """드롭은 곧 비용 과소 집계입니다. 조용한 유실이 가장 나쁜 실패 형태입니다."""
    recorder = UsageRecorder(spool_max=2)
    for i in range(5):
        await recorder.record(None, _record(f"r{i}"))
    assert recorder.spool_size == 2
    assert recorder.dropped == 3


async def test_drain_without_database_keeps_the_spool():
    recorder = UsageRecorder(spool_max=10)
    await recorder.record(None, _record("r1"))
    assert await recorder.drain(None) == 0
    assert recorder.spool_size == 1


@pytest.mark.parametrize("status", ["SUCCESS", "ERROR", "TIMEOUT"])
def test_row_shape_matches_the_column_contract(status: str):
    row = _record("r1").to_row()
    row["status"] = status
    assert set(row) == {
        "id", "request_id", "occurred_at", "team_id", "user_id", "virtual_key_id",
        "model_alias", "provider_model_id", "dialect", "status",
        "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
        "estimated_usage", "latency_ms", "ttft_ms", "is_streaming",
        "estimated_cost_usd", "pricing_id", "error_code", "client",
    }
