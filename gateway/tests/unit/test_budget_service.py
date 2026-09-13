"""예산 집행과 누적.

여기서 고정하는 것은 셋입니다 — **미설정도 캐시한다**, **"키 없음"과 "확인 불가"를 구분한다**,
**확인 불가는 fail-open 이되 조용하지 않다**(docs/08).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from gateway.core import cache_keys
from gateway.core.clock import month_period
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.services.budget_service import BudgetService, format_amount
from tests.fakes import FakeRedis

TEAM_ID = "33333333-3333-3333-3333-333333333333"
USER_ID = "22222222-2222-2222-2222-222222222222"


class CounterBlind(FakeRedis):
    """설정은 읽히지만 카운터 조회만 실패하는 Redis. 부분 장애를 재현합니다."""

    async def get(self, key: str):
        if key.startswith("budget:usage:"):
            raise ConnectionError("counter unavailable")
        return await super().get(key)


def auth(user_id: str | None = USER_ID) -> AuthContext:
    return AuthContext(
        virtual_key_id="11111111-1111-1111-1111-111111111111",
        owner_type="USER" if user_id else "TEAM",
        owner_id=user_id or TEAM_ID,
        team_id=TEAM_ID,
        user_id=user_id,
        status="ACTIVE",
        expires_at=None,
        allowed_model_aliases=("claude-sonnet",),
    )


async def put_config(redis, scope, scope_id, limit, policy="HARD_BLOCK"):
    await redis.setex(
        cache_keys.budget_policy(scope, scope_id),
        300,
        json.dumps({"set": True, "limit_usd": limit, "policy": policy}),
    )


async def put_used(redis, scope, scope_id, used):
    await redis.setex(
        cache_keys.budget_usage_counter(scope, scope_id, month_period()), 300, used
    )


@pytest.fixture
def service(settings) -> BudgetService:
    return BudgetService(settings)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


async def test_no_config_passes(service, redis):
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    assert not outcome.verdict.blocked
    assert not outcome.degraded


async def test_negative_cache_is_honoured(service, redis):
    """미설정을 캐시하지 않으면 예산 없는 팀의 모든 요청이 DB 를 봅니다."""
    await redis.setex(cache_keys.budget_policy("team", TEAM_ID), 300, json.dumps({"set": False}))
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    assert not outcome.verdict.blocked


async def test_missing_counter_means_zero_not_unknown(service, redis):
    """그 달의 첫 요청입니다. 확인 불가가 아닙니다."""
    await put_config(redis, "team", TEAM_ID, "100.0000")
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    assert not outcome.verdict.blocked
    assert not outcome.degraded
    assert outcome.team_limit == Decimal("100.0000")


async def test_exhausted_team_budget_blocks(service, redis):
    await put_config(redis, "team", TEAM_ID, "100.0000")
    await put_used(redis, "team", TEAM_ID, "100.0001")
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)

    with pytest.raises(GatewayError) as excinfo:
        service.enforce(outcome)
    err = excinfo.value
    assert err.code is ErrorCode.BUDGET_EXCEEDED
    assert err.status == 429
    assert err.outcome is AuthOutcome.BUDGET_EXCEEDED
    # 월 예산 초과는 기다려서 풀리는 상태가 아닙니다.
    assert err.retry_after is None


async def test_soft_warn_does_not_block(service, redis):
    await put_config(redis, "team", TEAM_ID, "10.0000", policy="SOFT_WARN")
    await put_used(redis, "team", TEAM_ID, "999.0000")
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    service.enforce(outcome)  # 예외가 나지 않아야 합니다
    assert outcome.verdict.warnings


async def test_team_owned_key_skips_the_user_layer(service, redis):
    await put_config(redis, "user", USER_ID, "0.0000")
    await put_used(redis, "user", USER_ID, "5.0000")
    outcome = await service.evaluate(auth=auth(user_id=None), redis=redis, session_factory=None)
    assert not outcome.verdict.blocked
    assert outcome.user_limit is None


async def test_unreadable_counter_fails_open_but_is_flagged(service):
    """Redis 순단이 전사 LLM 장애가 되면 안 됩니다. 대신 조용하지 않습니다."""
    redis = CounterBlind()
    await put_config(redis, "team", TEAM_ID, "1.0000")
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    assert not outcome.verdict.blocked
    assert outcome.degraded


async def test_accumulate_writes_a_parsable_counter(service, redis):
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    await service.accumulate(
        redis=redis,
        session_factory=None,
        auth=auth(),
        outcome=outcome,
        cost=Decimal("0.000045"),
    )
    team_key = cache_keys.budget_usage_counter("team", TEAM_ID, month_period())
    user_key = cache_keys.budget_usage_counter("user", USER_ID, month_period())
    for key in (team_key, user_key):
        raw = redis.value(key)
        assert "E" not in raw and "e" not in raw  # INCRBYFLOAT 는 지수 표기를 읽지 못합니다
        assert Decimal(raw) == Decimal("0.0000")  # numeric(14,4) 로 반내림된 값


async def test_accumulate_skips_zero_cost(service, redis):
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    await service.accumulate(
        redis=redis, session_factory=None, auth=auth(), outcome=outcome, cost=Decimal("0")
    )
    assert not redis.has(cache_keys.budget_usage_counter("team", TEAM_ID, month_period()))


async def test_accumulate_sets_expiry_only_once(service, redis):
    outcome = await service.evaluate(auth=auth(), redis=redis, session_factory=None)
    key = cache_keys.budget_usage_counter("team", TEAM_ID, month_period())

    await service.accumulate(
        redis=redis, session_factory=None, auth=auth(), outcome=outcome, cost=Decimal("1")
    )
    first = redis.ttl(key)
    await service.accumulate(
        redis=redis, session_factory=None, auth=auth(), outcome=outcome, cost=Decimal("1")
    )
    # NX 라 진행 중인 달의 만료가 계속 밀려나지 않습니다.
    assert redis.ttl(key) == first
    assert Decimal(redis.value(key)) == Decimal("2")


@pytest.mark.parametrize(
    "value", ["0.00001", "1E+2", "123456789.1234", "0.0001"]
)
def test_format_amount_never_uses_exponent_notation(value):
    assert "E" not in format_amount(Decimal(value)).upper()
