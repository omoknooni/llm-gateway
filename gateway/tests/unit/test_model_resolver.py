"""모델 해석의 캐시·거절 경로."""

from __future__ import annotations

import pytest

from gateway.config import Settings
from gateway.core import cache_keys
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.services.model_resolver import ModelResolver
from tests.fakes import FakeRedis
from tests.unit.test_model_config import make


@pytest.fixture
def resolver() -> ModelResolver:
    return ModelResolver(Settings())


async def test_cache_hit_skips_the_database(resolver):
    redis = FakeRedis()
    import json

    await redis.setex(cache_keys.model_policy("claude-sonnet"), 300, json.dumps(make().to_dict()))

    config = await resolver.resolve(model_ref="claude-sonnet", redis=redis, session_factory=None)
    assert config.provider_model_id.endswith("claude-sonnet-4-5-20250929-v1:0")


async def test_inactive_model_is_refused_not_rerouted(resolver):
    """운영자의 kill switch 입니다. 조용히 다른 모델로 우회시키면 비용 추적이 불가능해집니다."""
    redis = FakeRedis()
    import json

    await redis.setex(
        cache_keys.model_policy("claude-sonnet"), 300, json.dumps(make(status="INACTIVE").to_dict())
    )

    with pytest.raises(GatewayError) as exc:
        await resolver.resolve(model_ref="claude-sonnet", redis=redis, session_factory=None)
    assert exc.value.code is ErrorCode.MODEL_INACTIVE
    assert exc.value.status == 404
    assert exc.value.outcome is AuthOutcome.MODEL_INACTIVE


async def test_mantle_without_endpoint_is_refused(resolver):
    """DB CHECK 는 새 행만 막습니다. 첫 호출에서 알 수 없는 실패를 내는 대신 여기서 끊습니다."""
    redis = FakeRedis()
    import json

    await redis.setex(
        cache_keys.model_policy("cowork-opus"),
        300,
        json.dumps(make(alias="cowork-opus", provider="BEDROCK_MANTLE", endpoint_url=None).to_dict()),
    )

    with pytest.raises(GatewayError) as exc:
        await resolver.resolve(model_ref="cowork-opus", redis=redis, session_factory=None)
    assert exc.value.code is ErrorCode.MODEL_INACTIVE


async def test_corrupt_cache_entry_falls_through_to_the_database(resolver):
    redis = FakeRedis()
    await redis.setex(cache_keys.model_policy("claude-sonnet"), 300, '{"alias": "only"}')

    with pytest.raises(GatewayError) as exc:
        await resolver.resolve(model_ref="claude-sonnet", redis=redis, session_factory=None)
    assert exc.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


async def test_rejection_message_does_not_distinguish_unknown_from_inactive(resolver):
    """구분해 주면 카탈로그에 무엇이 있는지 열거할 수 있게 됩니다."""
    redis = FakeRedis()
    import json

    await redis.setex(
        cache_keys.model_policy("gone"), 300, json.dumps(make(alias="gone", status="INACTIVE").to_dict())
    )
    with pytest.raises(GatewayError) as inactive:
        await resolver.resolve(model_ref="gone", redis=redis, session_factory=None)

    assert "is not available" in inactive.value.message
    assert "INACTIVE" not in inactive.value.message


async def test_active_aliases_uses_the_shared_cache_key(resolver):
    """허용 모델 해석과 같은 키를 씁니다. 두 곳이 각자 캐시하면 무효화가 한쪽에만 닿습니다."""
    redis = FakeRedis()
    import json

    await redis.setex(cache_keys.model_list(), 300, json.dumps(["a", "b"]))
    assert await resolver.active_aliases(redis=redis, session_factory=None) == ("a", "b")
