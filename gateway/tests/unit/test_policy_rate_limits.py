"""rate limit 두 축 해석 (공유 계약 — backend 06)."""

from __future__ import annotations

from gateway.policy.rate_limits import ALL_MODELS, GLOBAL_ID, LimitConfig, resolve


def test_nothing_defined():
    assert resolve([]).empty


def test_most_specific_wins():
    limits = resolve(
        [
            LimitConfig("USER", "u1", None, rpm_limit=100),
            LimitConfig("TEAM", "t1", None, rpm_limit=600),
        ]
    )
    assert limits.rpm.value == 100
    assert limits.rpm.scope == "USER"


def test_null_falls_through_per_limit_type():
    """한 요청에서 rpm 은 USER, tpm 은 TEAM 이 이길 수 있습니다.

    `NULL` 은 "정의되지 않음"이라 그 종류만 다음 후보로 넘어갑니다.
    """
    limits = resolve(
        [
            LimitConfig("USER", "u1", None, rpm_limit=100),
            LimitConfig("TEAM", "t1", None, rpm_limit=600, tpm_limit=50_000),
        ]
    )
    assert (limits.rpm.value, limits.rpm.scope) == (100, "USER")
    assert (limits.tpm.value, limits.tpm.scope) == (50_000, "TEAM")
    assert limits.concurrency is None


def test_model_dimension_beats_all_models_in_the_same_scope():
    limits = resolve(
        [
            LimitConfig("USER", "u1", "claude-sonnet", rpm_limit=10),
            LimitConfig("USER", "u1", None, rpm_limit=100),
        ]
    )
    assert limits.rpm.value == 10
    assert limits.rpm.model_alias == "claude-sonnet"


def test_counter_identity_follows_the_winning_config():
    """카운터는 **이긴 설정의 scope** 를 따라갑니다.

    한도가 사용자 것인데 팀 단위로 세면 설정한 의미와 다른 것을 재게 됩니다.
    """
    limits = resolve(
        [
            LimitConfig("VIRTUAL_KEY", "k1", None, rpm_limit=5),
            LimitConfig("TEAM", "t1", None, rpm_limit=600, tpm_limit=1000),
        ]
    )
    assert (limits.rpm.scope, limits.rpm.scope_id) == ("VIRTUAL_KEY", "k1")
    assert (limits.tpm.scope, limits.tpm.scope_id) == ("TEAM", "t1")


def test_all_models_and_global_placeholders():
    limits = resolve([LimitConfig("GLOBAL", None, None, rpm_limit=2000)])
    assert limits.rpm.scope_id == GLOBAL_ID
    assert limits.rpm.model_alias == ALL_MODELS


def test_iteration_order_is_cheapest_first():
    limits = resolve([LimitConfig("TEAM", "t1", None, rpm_limit=1, tpm_limit=2, concurrency_limit=3)])
    assert [x.limit_type for x in limits] == ["rpm", "tpm", "concurrency"]


def test_config_round_trips_through_cache_shape():
    config = LimitConfig("USER", "u1", "claude-sonnet", rpm_limit=1, concurrency_limit=2)
    assert LimitConfig.from_dict(config.to_dict()) == config
