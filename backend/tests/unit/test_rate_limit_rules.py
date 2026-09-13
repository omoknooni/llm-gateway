"""rate limit 해석 규칙 테스트 (M8).

07 문서가 "반드시 테스트로 고정할 규칙"으로 지목한 것 중 rate limit 몫입니다 —
**한도 종류별 폴백**과 **GLOBAL 별도 축**. 문서만으로는 구현이 갈리는 지점입니다.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core import cache_keys
from app.models.enums import RateLimitScope
from app.policy import rate_limit as policy
from app.policy.rate_limit import LimitCandidate
from app.schemas.rate_limits import RateLimitSetRequest

TEAM = RateLimitScope.TEAM
USER = RateLimitScope.USER
VK = RateLimitScope.VIRTUAL_KEY
GLOBAL = RateLimitScope.GLOBAL


def _c(scope, *, model=False, rpm=None, tpm=None, conc=None, config_id=None) -> LimitCandidate:
    return LimitCandidate(
        config_id=config_id or uuid.uuid4(),
        scope=scope,
        model_scoped=model,
        rpm_limit=rpm,
        tpm_limit=tpm,
        concurrency_limit=conc,
    )


# ── 구체성 순서 ──


def test_candidate_order_is_specific_first():
    """`VIRTUAL_KEY(model)` → `VIRTUAL_KEY(all)` → `USER(model)` → ... → `TEAM(all)`."""
    ordered = policy.order_candidates(
        [
            _c(TEAM),
            _c(VK, model=True),
            _c(USER),
            _c(TEAM, model=True),
            _c(VK),
            _c(USER, model=True),
        ]
    )
    assert [(c.scope, c.model_scoped) for c in ordered] == [
        (VK, True),
        (VK, False),
        (USER, True),
        (USER, False),
        (TEAM, True),
        (TEAM, False),
    ]


def test_model_scoped_beats_all_models_in_same_scope():
    resolution = policy.resolve([_c(USER, rpm=100), _c(USER, model=True, rpm=30)])
    assert resolution.rpm_limit.value == 30
    assert resolution.rpm_limit.resolved_from == "USER:model"


# ── 한도 종류별 독립 폴백 (핵심 규칙) ──


def test_each_limit_type_falls_back_independently():
    """`USER` 가 tpm 만 정의하면 rpm 은 `TEAM` 에서 옵니다.

    행 단위로 "가장 구체적인 행 하나"를 고르면 부분 정의가 상위의 다른 한도까지 지웁니다.
    """
    resolution = policy.resolve([_c(USER, tpm=50000), _c(TEAM, rpm=600, tpm=400000, conc=40)])

    assert resolution.rpm_limit.value == 600
    assert resolution.rpm_limit.resolved_from == "TEAM"
    assert resolution.tpm_limit.value == 50000
    assert resolution.tpm_limit.resolved_from == "USER"
    assert resolution.concurrency_limit.value == 40


def test_most_specific_wins_without_min_or_sum():
    """합산하지도, 최소값을 취하지도 않습니다.

    최소값을 취하면 상위에 낮은 값을 두는 것만으로 하위 설정이 무의미해져, 운영자가
    "왜 이 한도인가"를 설명할 수 없게 됩니다.
    """
    resolution = policy.resolve([_c(TEAM, rpm=600), _c(USER, rpm=1000)])
    assert resolution.rpm_limit.value == 1000  # 최소값 600 이 아닙니다
    assert resolution.rpm_limit.resolved_from == "USER"


def test_null_means_undefined_not_zero():
    """`NULL` 은 "이 층에서 정의 안 함"입니다. 다음 후보로 넘어갑니다."""
    resolution = policy.resolve([_c(VK, rpm=None, tpm=None, conc=5), _c(TEAM, rpm=600)])
    assert resolution.concurrency_limit.value == 5
    assert resolution.rpm_limit.value == 600


def test_undefined_limit_is_not_enforced():
    resolution = policy.resolve([_c(TEAM, rpm=600)])
    assert resolution.concurrency_limit.value is None
    assert resolution.concurrency_limit.resolved_from is None
    assert not resolution.concurrency_limit.defined


def test_no_candidates_resolves_to_nothing():
    resolution = policy.resolve([])
    assert not resolution.any_defined


def test_resolved_from_carries_config_id():
    """화면이 "이 한도는 어느 설정에서 왔는가"로 이동할 수 있어야 합니다."""
    config_id = uuid.uuid4()
    resolution = policy.resolve([_c(TEAM, rpm=600, config_id=config_id)])
    assert resolution.rpm_limit.config_id == str(config_id)


# ── GLOBAL 별도 축 ──


def test_global_is_not_part_of_subject_axis():
    """GLOBAL 을 주체 축에 섞으면 팀 한도가 더 구체적이라는 이유로 전역 상한이 사라집니다."""
    subject, global_axis = policy.split_axes(
        [_c(TEAM, rpm=600), _c(GLOBAL, model=True, rpm=2000)]
    )
    assert [c.scope for c in subject] == [TEAM]
    assert [c.scope for c in global_axis] == [GLOBAL]


def test_global_and_subject_resolve_separately():
    """둘 다 통과해야 요청이 진행됩니다 — 한쪽이 다른 쪽을 덮지 않습니다."""
    candidates = [_c(TEAM, rpm=600), _c(GLOBAL, model=True, rpm=2000)]
    subject, global_axis = policy.split_axes(candidates)

    assert policy.resolve(subject).rpm_limit.value == 600
    assert policy.resolve(global_axis).rpm_limit.value == 2000
    assert policy.resolve(global_axis).rpm_limit.resolved_from == "GLOBAL:model"


def test_global_falls_back_from_model_to_all():
    subject, global_axis = policy.split_axes(
        [_c(GLOBAL, model=True, rpm=2000), _c(GLOBAL, tpm=999999)]
    )
    resolution = policy.resolve(global_axis)
    assert resolution.rpm_limit.value == 2000
    assert resolution.tpm_limit.value == 999999
    assert subject == []


# ── 계층 제약 ──


def test_child_within_parent_passes():
    parent = policy.resolve([_c(TEAM, rpm=600, tpm=400000)])
    assert policy.check_within_parent({"rpm_limit": 100, "tpm_limit": 400000}, parent) == []


def test_child_exceeding_parent_is_reported_per_field():
    parent = policy.resolve([_c(TEAM, rpm=600, tpm=400000)])
    violations = policy.check_within_parent(
        {"rpm_limit": 1000, "tpm_limit": 100, "concurrency_limit": 5}, parent
    )
    assert [v.field for v in violations] == ["rpm_limit"]
    assert violations[0].value == 1000
    assert violations[0].parent_value == 600
    assert violations[0].parent_resolved_from == "TEAM"


def test_parent_without_definition_is_no_constraint():
    """없는 상한을 넘을 수는 없습니다."""
    parent = policy.resolve([_c(TEAM, rpm=600)])
    assert policy.check_within_parent({"concurrency_limit": 9999}, parent) == []


def test_conflicting_children_are_listed_not_rejected():
    """팀 한도를 낮출 때 더 큰 멤버 한도는 **경고**입니다. 연쇄 자동 조정은 하지 않습니다."""
    child_a, child_b = str(uuid.uuid4()), str(uuid.uuid4())
    conflicts = policy.find_conflicting_children(
        {"rpm_limit": 100, "tpm_limit": None, "concurrency_limit": None},
        [
            (child_a, {"rpm_limit": 500, "tpm_limit": None, "concurrency_limit": None}),
            (child_b, {"rpm_limit": 50, "tpm_limit": None, "concurrency_limit": None}),
        ],
    )
    assert len(conflicts) == 1
    assert conflicts[0]["scope_id"] == child_a
    assert conflicts[0]["exceeds"]["rpm_limit"] == {"child": 500, "parent": 100}


# ── 설정 의미 ──


def test_all_null_limits_are_rejected():
    """세 한도가 모두 비면 행 삭제와 구분되지 않습니다(06 문서)."""
    with pytest.raises(PydanticValidationError):
        RateLimitSetRequest()


@pytest.mark.parametrize("field", ["rpm_limit", "tpm_limit", "concurrency_limit"])
def test_zero_limit_is_rejected(field):
    """`0` 은 "전면 차단"입니다. 차단이 필요하면 VK 를 폐기하거나 사용자를 비활성화합니다."""
    with pytest.raises(PydanticValidationError):
        RateLimitSetRequest(**{field: 0})


@pytest.mark.parametrize("field", ["rpm_limit", "tpm_limit", "concurrency_limit"])
def test_single_limit_is_enough(field):
    """부분 정의는 정상입니다 — 나머지는 상위로 폴백합니다."""
    request = RateLimitSetRequest(**{field: 10})
    assert getattr(request, field) == 10


# ── 캐시 키 (공유 계약) ──


def test_policy_key_shape():
    scope_id = uuid.UUID("9f2c0000-0000-0000-0000-000000000001")
    assert (
        cache_keys.rate_limit_policy("TEAM", scope_id, "claude-sonnet-4")
        == f"policy:ratelimit:team:{scope_id}:claude-sonnet-4"
    )
    # 모델 전체는 '*', GLOBAL 은 대상이 없어 'global' 입니다.
    assert cache_keys.rate_limit_policy("TEAM", scope_id, None) == f"policy:ratelimit:team:{scope_id}:*"
    assert cache_keys.rate_limit_policy("GLOBAL", None, "m") == "policy:ratelimit:global:global:m"


def test_counter_key_never_matches_policy_prefix():
    """설정 캐시와 집행 카운터는 접두사가 달라야 합니다.

    겹치면 설정 무효화가 카운터까지 지워 **진행 중인 윈도가 리셋되고 한도가 뚫립니다**(06 문서).
    """
    scope_id = uuid.uuid4()
    counter = cache_keys.rate_limit_counter("USER", scope_id, "claude-sonnet-4", "60s")
    assert counter.startswith("rl:")
    assert not counter.startswith("policy:ratelimit:")
