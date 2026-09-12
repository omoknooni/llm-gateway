"""예산 판정 (공유 계약 — backend 05 의 판정 순서)."""

from __future__ import annotations

from decimal import Decimal

from gateway.policy.budget import HARD_BLOCK, SOFT_WARN, BudgetState, evaluate


def state(scope="USER", used="10", limit="10", policy=HARD_BLOCK) -> BudgetState:
    return BudgetState(
        scope=scope,
        scope_id="id",
        limit_usd=Decimal(limit),
        policy=policy,
        used_usd=Decimal(used),
    )


def test_nothing_set_passes():
    assert not evaluate(None, None).blocked


def test_under_limit_passes():
    assert not evaluate(state(used="9.9999", limit="10")).blocked


def test_exactly_at_limit_is_exceeded():
    """`>=` 입니다. `>` 로 두면 한도 0(= 쓸 수 없음)이 사실상 무제한이 됩니다."""
    assert evaluate(state(used="10", limit="10")).blocked


def test_zero_limit_blocks_any_usage():
    assert evaluate(state(used="0", limit="0")).blocked


def test_team_blocks_even_when_user_has_room():
    """하위가 상위를 우회할 수 있으면 팀 한도는 장식입니다."""
    verdict = evaluate(
        state(scope="USER", used="1", limit="100"),
        state(scope="TEAM", used="500", limit="500"),
    )
    assert verdict.blocked
    assert verdict.blocked_by.scope == "TEAM"


def test_user_layer_wins_as_the_reported_reason():
    """둘 다 초과면 **사용자 층**이 사유가 됩니다 — 본인이 고칠 수 있는 것을 알려줍니다."""
    verdict = evaluate(
        state(scope="USER", used="100", limit="100"),
        state(scope="TEAM", used="500", limit="500"),
    )
    assert verdict.blocked_by.scope == "USER"


def test_soft_warn_passes_but_is_reported():
    verdict = evaluate(state(used="200", limit="100", policy=SOFT_WARN))
    assert not verdict.blocked
    assert [w.scope for w in verdict.warnings] == ["USER"]


def test_soft_warn_user_does_not_hide_hard_block_team():
    verdict = evaluate(
        state(scope="USER", used="200", limit="100", policy=SOFT_WARN),
        state(scope="TEAM", used="500", limit="500", policy=HARD_BLOCK),
    )
    assert verdict.blocked
    assert verdict.blocked_by.scope == "TEAM"
    assert [w.scope for w in verdict.warnings] == ["USER"]
