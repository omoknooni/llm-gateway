"""집행이 파이프라인의 제자리에서 일어나는지 (docs/08).

미들웨어가 아니라 **라우터 단계**이고, 예산(읽기)이 rate limit(카운터 증가)보다 먼저이며,
거절되면 provider 를 부르지 않고, 통과하면 Finalize 가 정산·반납·누적을 전부 지나야 합니다.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from gateway.core import cache_keys
from gateway.core.clock import epoch_minute, month_period
from gateway.policy.rate_limits import LimitConfig
from tests.api.conftest import auth_header, body

TEAM_ID = "33333333-3333-3333-3333-333333333333"
USER_ID = "22222222-2222-2222-2222-222222222222"
ALIAS = "claude-sonnet"

PATHS = {
    "/v1/messages": body(),
    "/v1/chat/completions": {"model": ALIAS, "messages": [{"role": "user", "content": "hi"}]},
}


def set_budget(client, redis, scope, scope_id, limit, used, policy="HARD_BLOCK"):
    client.portal.call(
        redis.setex,
        cache_keys.budget_policy(scope, scope_id),
        300,
        json.dumps({"set": True, "limit_usd": limit, "policy": policy}),
    )
    client.portal.call(
        redis.setex,
        cache_keys.budget_usage_counter(scope, scope_id, month_period()),
        300,
        used,
    )


def set_limit(client, redis, scope, scope_id, alias, **limits):
    config = LimitConfig(scope=scope, scope_id=scope_id, model_alias=alias, **limits)
    client.portal.call(
        redis.setex,
        cache_keys.rate_limit_policy(scope, scope_id, alias),
        300,
        json.dumps({"set": True, "config": config.to_dict()}),
    )


def drain(client):
    client.portal.call(client.app.state.background.drain)


def rejections(client):
    return client.app.state.auth_events.pop_expired(force=True)


# ── 예산 ──


@pytest.mark.parametrize("path", list(PATHS))
def test_exhausted_budget_blocks_both_dialects(client, redis, adapter, path):
    set_budget(client, redis, "team", TEAM_ID, "10.0000", "10.0000")

    response = client.post(path, headers=auth_header(), json=PATHS[path])

    assert response.status_code == 429
    assert adapter.calls == []  # provider 를 부르지 않았습니다
    # 기다려서 풀리는 상태가 아니므로 Retry-After 를 붙이지 않습니다.
    assert "retry-after" not in response.headers


def test_budget_rejection_goes_to_auth_events(client, redis):
    set_budget(client, redis, "team", TEAM_ID, "10.0000", "10.0000")
    client.post("/v1/messages", headers=auth_header(), json=body())

    rows = rejections(client)
    assert [r["outcome"] for r in rows] == ["BUDGET_EXCEEDED"]
    assert rows[0]["team_id"] == TEAM_ID


def test_soft_warn_budget_lets_the_call_through(client, redis, adapter):
    set_budget(client, redis, "team", TEAM_ID, "1.0000", "999.0000", policy="SOFT_WARN")
    response = client.post("/v1/messages", headers=auth_header(), json=body())

    assert response.status_code == 200
    assert len(adapter.calls) == 1


def test_successful_call_accumulates_the_budget_counter(client, redis):
    client.post("/v1/messages", headers=auth_header(), json=body())
    drain(client)

    for scope, scope_id in (("team", TEAM_ID), ("user", USER_ID)):
        raw = redis.value(cache_keys.budget_usage_counter(scope, scope_id, month_period()))
        assert raw is not None and Decimal(raw) > 0


# ── rate limit ──


def test_rpm_limit_blocks_the_second_call(client, redis, adapter):
    set_limit(client, redis, "USER", USER_ID, None, rpm_limit=1)

    assert client.post("/v1/messages", headers=auth_header(), json=body()).status_code == 200
    second = client.post("/v1/messages", headers=auth_header(), json=body())

    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert len(adapter.calls) == 1


def test_rate_limit_rejection_goes_to_auth_events(client, redis):
    set_limit(client, redis, "USER", USER_ID, None, rpm_limit=1)
    client.post("/v1/messages", headers=auth_header(), json=body())
    client.post("/v1/messages", headers=auth_header(), json=body())

    assert "RATE_LIMITED" in [r["outcome"] for r in rejections(client)]


def test_budget_is_checked_before_the_rate_limit_counter_moves(client, redis, adapter):
    """어차피 막힐 요청이 rate limit 윈도를 소모하면 안 됩니다(docs/08 의 4a → 4b)."""
    set_budget(client, redis, "team", TEAM_ID, "10.0000", "10.0000")
    set_limit(client, redis, "USER", USER_ID, None, rpm_limit=10)

    client.post("/v1/messages", headers=auth_header(), json=body())

    key = cache_keys.rate_limit_counter("user", USER_ID, "*", f"rpm:{epoch_minute()}")
    assert not redis.has(key)
    assert adapter.calls == []


def test_concurrency_slot_is_released_after_a_non_streaming_call(client, redis):
    set_limit(client, redis, "USER", USER_ID, None, concurrency_limit=1)
    key = cache_keys.rate_limit_counter("user", USER_ID, "*", "conc")

    for _ in range(3):
        assert client.post("/v1/messages", headers=auth_header(), json=body()).status_code == 200
        drain(client)
        assert redis.value(key) == "0"


def test_concurrency_slot_is_released_after_a_stream(client, redis):
    """스트림이 끝나는 지점을 미들웨어는 모릅니다. 반납이 Finalize 에 있는 이유입니다."""
    set_limit(client, redis, "USER", USER_ID, None, concurrency_limit=1)
    key = cache_keys.rate_limit_counter("user", USER_ID, "*", "conc")

    with client.stream("POST", "/v1/messages", headers=auth_header(), json=body(stream=True)) as r:
        assert r.status_code == 200
        list(r.iter_lines())
    drain(client)

    assert redis.value(key) == "0"


def test_tpm_is_settled_to_the_actual_usage(client, redis):
    set_limit(client, redis, "USER", USER_ID, None, tpm_limit=100_000)
    key = cache_keys.rate_limit_counter("user", USER_ID, "*", f"tpm:{epoch_minute()}")

    client.post("/v1/messages", headers=auth_header(), json=body())
    drain(client)

    # 대역 adapter 의 usage 는 11 + 3 입니다. 선차감(입력 추정 + max_tokens 64)이 정산됐습니다.
    assert redis.value(key) == "14"
