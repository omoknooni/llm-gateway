"""허용 모델 3층 해석 테스트.

문서만으로는 구현이 갈리는 지점입니다. **"행 0개"의 의미가 층마다 다릅니다.**
  - user 층 0개  = 폴백 (전체 허용 아님)
  - team 층 0개  = 제한 없음
  - VK 층 0개    = 축소 없음
gateway 가 같은 규칙을 구현하므로(08 문서 C3) 이 테스트가 계약의 실행 가능한 형태입니다.
"""

from __future__ import annotations

import pytest

from app.policy.allowed_models import ResolvedFrom, resolve

CATALOG = ["claude-sonnet-4", "claude-haiku-4", "nova-pro", "nova-lite"]


def test_no_policy_falls_back_to_active_catalog():
    result = resolve(catalog_active=CATALOG)
    assert result.aliases == sorted(CATALOG)
    assert result.resolved_from is ResolvedFrom.CATALOG
    assert result.narrowed_by_key is False


def test_team_policy_restricts():
    result = resolve(catalog_active=CATALOG, team_allowed=["nova-pro", "nova-lite"])
    assert result.aliases == ["nova-lite", "nova-pro"]
    assert result.resolved_from is ResolvedFrom.TEAM


def test_user_policy_overrides_team():
    """사용자 override 는 팀 정책을 덮어씁니다. 교집합이 아닙니다."""
    result = resolve(
        catalog_active=CATALOG,
        team_allowed=["nova-pro", "nova-lite"],
        user_allowed=["claude-sonnet-4"],
    )
    assert result.aliases == ["claude-sonnet-4"]
    assert result.resolved_from is ResolvedFrom.USER


def test_empty_user_policy_falls_back_to_team_not_all():
    """사용자 층의 0개는 '전체 허용'이 아니라 '팀 정책 따름'입니다."""
    result = resolve(catalog_active=CATALOG, team_allowed=["nova-pro"], user_allowed=[])
    assert result.aliases == ["nova-pro"]
    assert result.resolved_from is ResolvedFrom.TEAM


def test_empty_team_policy_means_unrestricted():
    """팀 층의 0개는 '제한 없음'입니다. 사용자 층과 의미가 다릅니다."""
    result = resolve(catalog_active=CATALOG, team_allowed=[])
    assert result.aliases == sorted(CATALOG)
    assert result.resolved_from is ResolvedFrom.CATALOG


def test_key_allowlist_narrows_by_intersection():
    result = resolve(
        catalog_active=CATALOG,
        team_allowed=["nova-pro", "nova-lite", "claude-haiku-4"],
        key_allowed=["nova-pro", "claude-sonnet-4"],
    )
    # claude-sonnet-4 는 소유자 정책에 없으므로 키가 지정해도 살아나지 않습니다.
    assert result.aliases == ["nova-pro"]
    assert result.narrowed_by_key is True


def test_empty_key_allowlist_means_no_narrowing():
    result = resolve(catalog_active=CATALOG, team_allowed=["nova-pro"], key_allowed=[])
    assert result.aliases == ["nova-pro"]
    assert result.narrowed_by_key is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"team_allowed": ["retired-model"]},
        {"user_allowed": ["retired-model"]},
        {"key_allowed": ["retired-model"], "team_allowed": ["retired-model", "nova-pro"]},
    ],
)
def test_inactive_alias_is_excluded_from_every_layer(kwargs):
    """카탈로그 상태가 최종 관문입니다. INACTIVE 는 어느 층에 있든 제외됩니다."""
    result = resolve(catalog_active=CATALOG, **kwargs)
    assert "retired-model" not in result.aliases


def test_key_narrowing_can_yield_empty_set():
    """교집합이 비면 그 키로는 어떤 모델도 호출할 수 없습니다. 조용히 전체 허용으로 넘어가지 않습니다."""
    result = resolve(catalog_active=CATALOG, team_allowed=["nova-pro"], key_allowed=["nova-lite"])
    assert result.aliases == []
    assert result.narrowed_by_key is True
