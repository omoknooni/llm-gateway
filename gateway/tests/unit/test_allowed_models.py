"""허용 모델 3층 해석 (공유 계약 C3).

backend 의 `policy/allowed_models.resolve()` 와 **같은 답**을 내야 합니다. 규칙이 갈리면
콘솔에는 허용인데 실제로는 차단되는 상태가 됩니다. 문서만으로는 구현이 갈리는 지점이라
테이블 주도로 고정합니다.
"""

from __future__ import annotations

import pytest

from gateway.policy.allowed_models import ResolvedFrom, resolve

CATALOG = ("claude-sonnet", "claude-haiku", "llama-3")


def test_no_policy_anywhere_means_whole_active_catalog():
    r = resolve(catalog_active=CATALOG)
    assert r.aliases == tuple(sorted(CATALOG))
    assert r.resolved_from is ResolvedFrom.CATALOG
    assert r.narrowed_by_key is False


def test_team_rows_limit_to_that_list():
    r = resolve(catalog_active=CATALOG, team_allowed=["claude-haiku"])
    assert r.aliases == ("claude-haiku",)
    assert r.resolved_from is ResolvedFrom.TEAM


def test_user_rows_override_team_entirely():
    """user 층은 팀 정책을 덮어씁니다. 교집합이 아닙니다."""
    r = resolve(
        catalog_active=CATALOG,
        team_allowed=["claude-haiku"],
        user_allowed=["claude-sonnet"],
    )
    assert r.aliases == ("claude-sonnet",)
    assert r.resolved_from is ResolvedFrom.USER


def test_empty_user_rows_fall_back_to_team_not_to_everything():
    """user 층의 0개는 *폴백*입니다. '전체 허용'이 아닙니다."""
    r = resolve(catalog_active=CATALOG, team_allowed=["claude-haiku"], user_allowed=[])
    assert r.aliases == ("claude-haiku",)
    assert r.resolved_from is ResolvedFrom.TEAM


def test_key_rows_narrow_by_intersection():
    r = resolve(
        catalog_active=CATALOG,
        team_allowed=["claude-haiku", "claude-sonnet"],
        key_allowed=["claude-sonnet", "llama-3"],
    )
    assert r.aliases == ("claude-sonnet",)  # 팀에 없는 llama-3 는 키로도 열 수 없습니다
    assert r.narrowed_by_key is True


def test_empty_key_rows_mean_no_narrowing():
    """VK 층의 0개는 *축소 없음*입니다. 여기서 빈 목록을 교집합하면 전부 막힙니다."""
    r = resolve(catalog_active=CATALOG, team_allowed=["claude-haiku"], key_allowed=[])
    assert r.aliases == ("claude-haiku",)
    assert r.narrowed_by_key is False


def test_inactive_alias_is_excluded_from_every_layer():
    """카탈로그 상태가 최종 관문입니다."""
    active = ("claude-sonnet",)
    r = resolve(
        catalog_active=active,
        team_allowed=["claude-haiku"],          # 카탈로그에서 내려간 모델
        user_allowed=["claude-haiku", "claude-sonnet"],
        key_allowed=["claude-haiku", "claude-sonnet"],
    )
    assert r.aliases == ("claude-sonnet",)


def test_key_narrowing_can_produce_empty_list():
    """빈 목록은 유효한 상태입니다 — 이 키로 쓸 수 있는 모델이 없다는 뜻."""
    r = resolve(catalog_active=CATALOG, team_allowed=["claude-haiku"], key_allowed=["llama-3"])
    assert r.aliases == ()


@pytest.mark.parametrize("layer", ["team_allowed", "user_allowed", "key_allowed"])
def test_result_is_sorted_and_deduplicated(layer: str):
    """캐시에 그대로 직렬화되므로 같은 입력이 항상 같은 문자열이어야 합니다."""
    r = resolve(catalog_active=CATALOG, **{layer: ["llama-3", "claude-haiku", "llama-3"]})
    assert r.aliases == ("claude-haiku", "llama-3")
