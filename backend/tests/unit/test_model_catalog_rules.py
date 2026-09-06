"""모델 카탈로그 규칙 테스트 (gateway 요청 S1·S2, Q1 반영분)."""

from __future__ import annotations

import pytest

from app.core import cache_keys
from app.core.exceptions import ValidationError
from app.models.enums import Provider
from app.schemas.models import ModelCreateRequest
from app.services.model_service import ModelService

_PRICING = {
    "input_price_per_1k": "0.003",
    "output_price_per_1k": "0.015",
    "effective_from": "2026-09-01T00:00:00Z",
}


def test_model_list_cache_key_shape():
    """gateway 와 공유하는 키 이름입니다(09 문서 Q1)."""
    assert cache_keys.model_list() == "policy:model:list"


def test_catalog_change_invalidates_alias_and_list():
    """목록 항목이 supported_dialects·max_output_tokens 를 실으므로 항상 함께 지웁니다.

    상태 전환만 트리거로 잡으면 방언이 바뀐 모델이 /v1/models 에 옛 값으로 남습니다.
    """
    assert ModelService._policy_keys("claude-sonnet-4") == [
        "policy:model:claude-sonnet-4",
        "policy:model:list",
    ]


def test_mantle_requires_endpoint_url():
    with pytest.raises(ValidationError) as exc:
        ModelService._validate_endpoint(Provider.BEDROCK_MANTLE, None)
    assert exc.value.code == "endpoint_url_required"


def test_mantle_with_endpoint_url_passes():
    ModelService._validate_endpoint(Provider.BEDROCK_MANTLE, "https://mantle.example/anthropic")


@pytest.mark.parametrize("endpoint", [None, "https://vpce.example"])
def test_bedrock_endpoint_is_optional(endpoint):
    """역방향(BEDROCK 인데 값이 있음)은 막지 않습니다. adapter 가 읽지 않아 무해합니다."""
    ModelService._validate_endpoint(Provider.BEDROCK, endpoint)


def _create_request(**overrides):
    payload = {
        "alias": "claude-sonnet-4",
        "provider_model_id": "apac.anthropic.claude-sonnet-4-v1:0",
        "supported_dialects": ["OPENAI_CHAT"],
        "pricing": _PRICING,
    }
    payload.update(overrides)
    return ModelCreateRequest(**payload)


def test_endpoint_url_must_be_https():
    """평문 HTTP 로 모델 호출이 나가지 않게 합니다."""
    with pytest.raises(ValueError, match="https"):
        _create_request(endpoint_url="http://mantle.example")


def test_endpoint_url_optional_and_https_accepted():
    assert _create_request().endpoint_url is None
    assert _create_request(endpoint_url="https://mantle.example").endpoint_url == "https://mantle.example"


def test_provider_enum_carries_mantle():
    """S1. 값 삭제는 하지 않으므로 이 목록은 앞으로 늘기만 합니다."""
    assert [p.value for p in Provider] == ["BEDROCK", "BEDROCK_MANTLE"]
