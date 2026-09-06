"""VK 인증의 캐시·장애 경로.

DB 를 타는 경로는 통합 테스트의 몫이고, 여기서는 **의존성이 죽었을 때 무엇을 하는지**를
고정합니다. 이 부분이 문서에만 있으면 구현이 갈립니다(docs/02 실패 정책).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from gateway.config import Settings
from gateway.core import cache_keys
from gateway.core.clock import utcnow
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.services.auth_service import AuthService, extract_token, hash_key
from tests.fakes import FakeRedis

KEY = "vk_live_abcdef0123456789"
KEY_HASH = hash_key(KEY)


def make_context(**overrides) -> AuthContext:
    base = {
        "virtual_key_id": "11111111-1111-1111-1111-111111111111",
        "owner_type": "USER",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "team_id": "33333333-3333-3333-3333-333333333333",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "status": "ACTIVE",
        "expires_at": None,
        "allowed_model_aliases": ("claude-sonnet",),
    }
    return AuthContext(**{**base, **overrides})


@pytest.fixture
def service() -> AuthService:
    return AuthService(Settings())


async def authenticate(service, redis, *, key: str = KEY, session_factory=None):
    return await service.authenticate(
        authorization=f"Bearer {key}", api_key="", redis=redis, session_factory=session_factory
    )


# ── 자격 증명 추출 ──


def test_authorization_wins_over_api_key():
    """두 헤더가 다를 때의 동작이 갈리지 않게 우선순위를 고정합니다."""
    assert extract_token("Bearer from-auth", "from-x-api-key") == "from-auth"


def test_x_api_key_is_accepted():
    """Anthropic client 는 관례적으로 x-api-key 를 씁니다."""
    assert extract_token("", "from-x-api-key") == "from-x-api-key"


def test_bearer_scheme_is_case_insensitive():
    assert extract_token("bearer tok", "") == "tok"


@pytest.mark.parametrize("authorization", ["", "Basic tok", "Bearer", "Bearer   "])
def test_missing_or_malformed_credentials_are_rejected(authorization: str):
    with pytest.raises(GatewayError) as exc:
        extract_token(authorization, "")
    assert exc.value.code is ErrorCode.INVALID_VIRTUAL_KEY
    assert exc.value.outcome is AuthOutcome.INVALID_KEY


def test_key_hash_is_the_shared_contract_formula():
    """알고리즘이나 인코딩을 한쪽만 바꾸면 전 키가 인증 실패합니다(C1)."""
    import hashlib

    assert hash_key(KEY) == hashlib.sha256(KEY.encode("utf-8")).hexdigest()
    assert len(hash_key(KEY)) == 64


# ── 캐시 경로 ──


async def test_cache_hit_skips_the_database(service):
    redis = FakeRedis()
    await redis.setex(cache_keys.vk_auth(KEY_HASH), 300, make_context().to_json())

    # session_factory 가 None 인데도 통과한다는 것은 DB 를 보지 않았다는 뜻입니다.
    context = await authenticate(service, redis)
    assert context.allowed_model_aliases == ("claude-sonnet",)


async def test_negative_cache_rejects_without_touching_the_database(service):
    redis = FakeRedis()
    await redis.setex(cache_keys.vk_miss(KEY_HASH), 30, "1")

    with pytest.raises(GatewayError) as exc:
        await authenticate(service, redis)
    assert exc.value.code is ErrorCode.INVALID_VIRTUAL_KEY


async def test_expired_snapshot_is_rejected_and_evicted(service):
    """캐시된 뒤 만료된 키가 TTL 동안 통과하면 안 됩니다.

    로테이션 유예가 expires_at 으로 표현되므로 흔한 경우입니다.
    """
    redis = FakeRedis()
    expired = make_context(expires_at=utcnow() - timedelta(seconds=1))
    await redis.setex(cache_keys.vk_auth(KEY_HASH), 300, expired.to_json())

    with pytest.raises(GatewayError) as exc:
        await authenticate(service, redis)
    assert exc.value.outcome is AuthOutcome.EXPIRED
    assert not redis.has(cache_keys.vk_auth(KEY_HASH))


async def test_future_expiry_still_passes(service):
    redis = FakeRedis()
    live = make_context(expires_at=utcnow() + timedelta(hours=1), status="ROTATED")
    await redis.setex(cache_keys.vk_auth(KEY_HASH), 300, live.to_json())

    context = await authenticate(service, redis)
    assert context.status == "ROTATED"  # 유예 중인 구 키는 통과합니다 (C1)


async def test_corrupt_cache_entry_is_treated_as_a_miss(service):
    """구버전 형식 하나가 영구 500 이 되는 것을 막습니다."""
    redis = FakeRedis()
    await redis.setex(cache_keys.vk_auth(KEY_HASH), 300, '{"unexpected": "shape"}')

    with pytest.raises(GatewayError) as exc:
        await authenticate(service, redis)
    # miss 로 취급 → DB 로 내려가야 하는데 DB 가 없으므로 "확인 불가"
    assert exc.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


# ── 장애 조합 (docs/README 실패 정책) ──


async def test_both_dependencies_down_is_unavailable_not_unauthorized(service):
    """의존성 장애를 401 로 답하면 client 는 멀쩡한 키를 로테이션합니다."""
    with pytest.raises(GatewayError) as exc:
        await authenticate(service, FakeRedis(failing=True))
    assert exc.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert exc.value.status == 503


async def test_unavailable_is_not_recorded_as_a_rejection(service):
    """확인하지 못한 것은 거절이 아닙니다. auth_events 에 남기지 않습니다."""
    with pytest.raises(GatewayError) as exc:
        await authenticate(service, None)
    assert exc.value.outcome is None


async def test_redis_failure_alone_does_not_reject(service):
    """캐시는 없어도 되는 것입니다. 조회 실패가 인증 실패로 번지면 안 됩니다."""
    redis = FakeRedis(failing=True)
    with pytest.raises(GatewayError) as exc:
        await authenticate(service, redis, session_factory=None)
    # DB 도 없으니 여기서는 503. Redis 실패 자체로 401 이 되지 않는 것이 핵심입니다.
    assert exc.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


# ── 스냅샷 ──


def test_snapshot_round_trip_preserves_every_field():
    context = make_context(expires_at=utcnow())
    assert AuthContext.from_json(context.to_json()) == context


def test_snapshot_carries_no_personal_identifier():
    """provider 로 보낼 식별자를 user_id 로 바꾼 결과, 캐시에 PII 가 없습니다(docs/06 Q4)."""
    payload = make_context().to_json()
    assert "idp_subject" not in payload
    assert "email" not in payload


def test_end_user_id_prefers_user_over_key():
    """VK 는 로테이션되지만 사람은 그대로입니다. provider 측 추적 연속성."""
    assert make_context().end_user_id == "22222222-2222-2222-2222-222222222222"
    team_key = make_context(owner_type="TEAM", user_id=None)
    assert team_key.end_user_id == team_key.virtual_key_id
