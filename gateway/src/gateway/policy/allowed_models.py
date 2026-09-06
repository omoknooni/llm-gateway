"""허용 모델 3층 해석.

**공유 계약 C3.** backend 의 `policy/allowed_models.resolve()` 와 같은 답을 내야 합니다.
규칙이 갈리면 "콘솔에는 허용인데 실제로는 차단"이 됩니다.

    1) 소유자 기본
         user_allowed 행 있음 → 그 목록 (팀 정책을 덮어씀)
         행 0개               → team_allowed
         team_allowed 도 0개  → 카탈로그의 ACTIVE 전체
    2) VK 축소
         key_allowed 행 있음  → 1) 과 교집합
         행 0개               → 1) 그대로
    3) INACTIVE alias 는 어느 층에 있든 제외 (카탈로그 상태가 최종 관문)

핵심은 **"행 0개"의 의미가 층마다 다르다는 것**입니다. user 층의 0개는 *폴백*,
team 층의 0개는 *제한 없음*, VK 층의 0개는 *축소 없음* 입니다. 이 셋을 "비었으면 전체 허용"
으로 뭉뚱그리는 순간 사용자 예외 정책이 조용히 무력화됩니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ResolvedFrom(StrEnum):
    USER = "USER"
    TEAM = "TEAM"
    CATALOG = "CATALOG"


@dataclass(frozen=True)
class AllowedModelResolution:
    aliases: tuple[str, ...]
    resolved_from: ResolvedFrom
    narrowed_by_key: bool


def resolve(
    *,
    catalog_active: Iterable[str],
    team_allowed: Iterable[str] = (),
    user_allowed: Iterable[str] = (),
    key_allowed: Iterable[str] = (),
) -> AllowedModelResolution:
    active = set(catalog_active)
    user_set, team_set, key_set = set(user_allowed), set(team_allowed), set(key_allowed)

    if user_set:
        base, resolved_from = user_set, ResolvedFrom.USER
    elif team_set:
        base, resolved_from = team_set, ResolvedFrom.TEAM
    else:
        base, resolved_from = active, ResolvedFrom.CATALOG

    narrowed = bool(key_set)
    if narrowed:
        base = base & key_set

    effective = base & active
    return AllowedModelResolution(
        aliases=tuple(sorted(effective)),
        resolved_from=resolved_from,
        narrowed_by_key=narrowed,
    )
