"""ModelConfig 의 캐시 왕복.

`pricing_id` 가 왕복에서 보존되는 것이 중요합니다. usage_events.pricing_id 를 채우지 못하면
"어떤 단가로 계산했는지"를 되짚을 수 없습니다(docs/04).
"""

from __future__ import annotations

from decimal import Decimal

from gateway.core.dialect import ApiDialect
from gateway.core.model import ModelConfig, ModelPricing


def make(**overrides) -> ModelConfig:
    base = {
        "alias": "claude-sonnet",
        "provider": "BEDROCK",
        "provider_model_id": "apac.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "region": "ap-northeast-2",
        "endpoint_url": None,
        "supported_dialects": ("ANTHROPIC_MESSAGES", "OPENAI_CHAT"),
        "status": "ACTIVE",
        "max_input_tokens": 200_000,
        "max_output_tokens": 8192,
        "supports_streaming": True,
        "pricing": ModelPricing(
            input_per_1k=Decimal("0.00300000"),
            output_per_1k=Decimal("0.01500000"),
            cache_write_per_1k=Decimal("0.00375000"),
            cache_read_per_1k=Decimal("0.00030000"),
        ),
        "pricing_id": "44444444-4444-4444-4444-444444444444",
    }
    return ModelConfig(**{**base, **overrides})


def test_round_trip_preserves_pricing_id():
    config = make()
    assert ModelConfig.from_dict(config.to_dict()) == config


def test_prices_survive_as_decimal_not_float():
    """부동소수점을 거치면 단가의 유효숫자가 조용히 깎입니다."""
    restored = ModelConfig.from_dict(make().to_dict())
    assert restored.pricing.input_per_1k == Decimal("0.00300000")
    assert isinstance(restored.pricing.input_per_1k, Decimal)


def test_model_without_pricing_round_trips():
    """단가 행이 없어도 호출은 됩니다. 비용만 0 으로 기록됩니다."""
    config = make(pricing=None, pricing_id=None)
    assert ModelConfig.from_dict(config.to_dict()) == config


def test_dialect_support_check():
    config = make(supported_dialects=("OPENAI_CHAT",))
    assert config.supports(ApiDialect.OPENAI_CHAT) is True
    assert config.supports(ApiDialect.ANTHROPIC_MESSAGES) is False
