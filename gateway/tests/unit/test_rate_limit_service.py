"""rate limit 집행.

되돌리기 규칙이 한도 종류마다 다르다는 것이 이 파일이 고정하는 핵심입니다 —
rpm 은 되돌리지 않고, tpm 은 애초에 차감하지 않으며, concurrency 는 되돌립니다(docs/08).
"""

from __future__ import annotations

import json

import pytest

from gateway.core import cache_keys
from gateway.core.clock import epoch_minute
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.core.normalized import Message, NormalizedRequest, TextBlock
from gateway.policy.rate_limits import LimitConfig
from gateway.services.rate_limit_service import RateLimitService
from tests.fakes import FakeRedis

TEAM_ID = "33333333-3333-3333-3333-333333333333"
USER_ID = "22222222-2222-2222-2222-222222222222"
KEY_ID = "11111111-1111-1111-1111-111111111111"
ALIAS = "claude-sonnet"


def auth(user_id: str | None = USER_ID) -> AuthContext:
    return AuthContext(
        virtual_key_id=KEY_ID,
        owner_type="USER" if user_id else "TEAM",
        owner_id=user_id or TEAM_ID,
        team_id=TEAM_ID,
        user_id=user_id,
        status="ACTIVE",
        expires_at=None,
        allowed_model_aliases=(ALIAS,),
    )


def request(text: str = "hi", max_tokens: int = 100) -> NormalizedRequest:
    return NormalizedRequest(
        model_alias=ALIAS,
        messages=[Message(role="user", content=[TextBlock(text=text)])],
        max_tokens=max_tokens,
        stream=False,
    )


async def put_limit(redis, scope, scope_id, alias, **limits):
    config = LimitConfig(scope=scope, scope_id=scope_id, model_alias=alias, **limits)
    await redis.setex(
        cache_keys.rate_limit_policy(scope, scope_id, alias),
        300,
        json.dumps({"set": True, "config": config.to_dict()}),
    )


@pytest.fixture
def service(settings) -> RateLimitService:
    return RateLimitService(settings)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


def counter(scope, scope_id, alias, window) -> str:
    return cache_keys.rate_limit_counter(scope, scope_id, alias, window)


async def charge(service, redis, **kwargs):
    return await service.charge(
        auth=kwargs.pop("auth", auth()),
        request=kwargs.pop("request", request()),
        model_alias=ALIAS,
        redis=redis,
        session_factory=None,
    )


# ── 없을 때 ──


async def test_no_limits_configured_is_a_no_op(service, redis):
    reservation = await charge(service, redis)
    assert reservation.empty


async def test_no_redis_fails_open(service):
    """셀 수 없으면 집행하지 않습니다. upstream 용량은 Bedrock 쿼터가 2차로 막습니다."""
    reservation = await service.charge(
        auth=auth(), request=request(), model_alias=ALIAS, redis=None, session_factory=None
    )
    assert reservation.empty


# ── rpm ──


async def test_rpm_blocks_past_the_limit(service, redis):
    await put_limit(redis, "USER", USER_ID, None, rpm_limit=2)
    await charge(service, redis)
    await charge(service, redis)

    with pytest.raises(GatewayError) as excinfo:
        await charge(service, redis)
    err = excinfo.value
    assert err.code is ErrorCode.RATE_LIMIT_EXCEEDED
    assert err.status == 429
    assert err.outcome is AuthOutcome.RATE_LIMITED
    # 윈도가 닫힐 때까지의 초. 즉시 재시도 폭주를 막습니다.
    assert 1 <= err.retry_after <= 60


async def test_rpm_rejection_is_not_rolled_back(service, redis):
    """거절된 요청도 도달한 요청입니다. 되돌리면 두드릴수록 통과 확률이 올라갑니다."""
    await put_limit(redis, "USER", USER_ID, None, rpm_limit=1)
    await charge(service, redis)
    with pytest.raises(GatewayError):
        await charge(service, redis)

    key = counter("USER", USER_ID, "*", f"rpm:{epoch_minute()}")
    assert redis.value(key) == "2"


async def test_counter_follows_the_winning_scope(service, redis):
    """VK 층이 이기면 카운터도 VK 단위여야 합니다."""
    await put_limit(redis, "VIRTUAL_KEY", KEY_ID, None, rpm_limit=5)
    await put_limit(redis, "TEAM", TEAM_ID, None, rpm_limit=600)
    await charge(service, redis)

    assert redis.value(counter("VIRTUAL_KEY", KEY_ID, "*", f"rpm:{epoch_minute()}")) == "1"
    assert not redis.has(counter("TEAM", TEAM_ID, "*", f"rpm:{epoch_minute()}"))


async def test_global_axis_is_enforced_alongside_the_subject_axis(service, redis):
    await put_limit(redis, "USER", USER_ID, None, rpm_limit=100)
    await put_limit(redis, "GLOBAL", None, ALIAS, rpm_limit=1)
    await charge(service, redis)

    with pytest.raises(GatewayError):
        await charge(service, redis)
    assert redis.value(counter("GLOBAL", "global", ALIAS, f"rpm:{epoch_minute()}")) == "2"


# ── tpm ──


async def test_tpm_rejects_without_charging(service, redis):
    """증가 후 비교로 하면 거절된 큰 요청 하나가 그 분 전체를 막습니다."""
    await put_limit(redis, "USER", USER_ID, None, tpm_limit=50)
    with pytest.raises(GatewayError):
        await charge(service, redis, request=request(max_tokens=1000))

    assert not redis.has(counter("USER", USER_ID, "*", f"tpm:{epoch_minute()}"))


async def test_tpm_precharges_then_settles_to_the_actual(service, redis):
    await put_limit(redis, "USER", USER_ID, None, tpm_limit=10_000)
    reservation = await charge(service, redis, request=request(max_tokens=500))

    key = counter("USER", USER_ID, "*", f"tpm:{epoch_minute()}")
    estimate = int(redis.value(key))
    assert estimate > 500  # 입력 추정 + max_tokens

    await service.finalize(redis, reservation, actual_tokens=42)
    assert redis.value(key) == "42"


async def test_tpm_settles_back_to_zero_when_the_call_never_happened(service, redis):
    await put_limit(redis, "USER", USER_ID, None, tpm_limit=10_000)
    reservation = await charge(service, redis)
    await service.finalize(redis, reservation, actual_tokens=None)

    key = counter("USER", USER_ID, "*", f"tpm:{epoch_minute()}")
    assert redis.value(key) == "0"


# ── concurrency ──


async def test_concurrency_slot_is_released(service, redis):
    await put_limit(redis, "USER", USER_ID, None, concurrency_limit=1)
    key = counter("USER", USER_ID, "*", "conc")

    reservation = await charge(service, redis)
    assert redis.value(key) == "1"
    await service.finalize(redis, reservation, actual_tokens=10)
    assert redis.value(key) == "0"


async def test_concurrency_rejection_rolls_back(service, redis):
    """게이지가 단조 증가하면 한도가 영구히 막힙니다."""
    await put_limit(redis, "USER", USER_ID, None, concurrency_limit=1)
    key = counter("USER", USER_ID, "*", "conc")

    held = await charge(service, redis)
    with pytest.raises(GatewayError) as excinfo:
        await charge(service, redis)
    assert excinfo.value.retry_after == 1  # 윈도가 없으므로 짧은 고정값

    assert redis.value(key) == "1"  # 거절된 쪽의 증가분이 남지 않았습니다
    await service.finalize(redis, held, actual_tokens=10)
    assert redis.value(key) == "0"


async def test_finalize_is_idempotent(service, redis):
    """두 번 반납하면 게이지가 음수로 새고 그 뒤로 한도가 사라집니다."""
    await put_limit(redis, "USER", USER_ID, None, concurrency_limit=2)
    key = counter("USER", USER_ID, "*", "conc")

    reservation = await charge(service, redis)
    await service.finalize(redis, reservation, actual_tokens=10)
    await service.finalize(redis, reservation, actual_tokens=10)
    assert redis.value(key) == "0"


async def test_concurrency_lease_has_a_ttl(service, redis, settings):
    """pod 가 스트림 도중 죽어도 슬롯이 영원히 남지 않아야 합니다."""
    await put_limit(redis, "USER", USER_ID, None, concurrency_limit=5)
    await charge(service, redis)
    assert redis.ttl(counter("USER", USER_ID, "*", "conc")) is not None


# ── 실패가 겹칠 때 ──


async def test_a_later_rejection_does_not_leak_earlier_reservations(service, redis):
    """tpm 에서 걸리면 그 전에 잡은 것이 남아 있으면 안 됩니다."""
    await put_limit(
        redis, "USER", USER_ID, None, rpm_limit=100, tpm_limit=1, concurrency_limit=100
    )
    with pytest.raises(GatewayError):
        await charge(service, redis)

    assert redis.value(counter("USER", USER_ID, "*", "conc")) in (None, "0")


# ── 추정 ──


def test_estimate_counts_input_and_reserves_max_tokens(service):
    estimate = service.estimate_tokens(request(text="a" * 40, max_tokens=100))
    assert estimate == 100 + 10  # 40자 / 4


def test_estimate_ignores_images(service, settings):
    """base64 길이는 토큰 수와 비례하지 않아, 세면 오히려 추정이 더 틀립니다."""
    from gateway.core.normalized import ImageBlock

    with_image = NormalizedRequest(
        model_alias=ALIAS,
        messages=[
            Message(role="user", content=[ImageBlock(media_type="image/png", data="x" * 10_000)])
        ],
        max_tokens=10,
        stream=False,
    )
    assert service.estimate_tokens(with_image) == 10
