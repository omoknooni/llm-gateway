"""허용 모델 해석.

> **공유 계약** — gateway 가 집행용으로 같은 규칙을 구현합니다(08 문서 C3). 규칙이 갈리면
> "화면에는 허용인데 실제로는 차단"이 됩니다.

세 층입니다.

```text
1) 소유자 기본
     user_allowed 행 있음 → 그 목록 (팀 정책을 덮어씀)
     행 0개               → team_allowed
     team_allowed 도 0개  → 카탈로그의 ACTIVE 전체
2) VK 축소
     vk_allowed 행 있음   → 1) 과 교집합
     행 0개               → 1) 그대로
3) INACTIVE alias 는 어느 층에 있든 제외
```

핵심은 **"행 0개"의 의미가 층마다 다르다는 것**입니다.
user 층의 0개는 *폴백*, team 층의 0개는 *제한 없음*, VK 층의 0개는 *축소 없음*입니다.
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
    aliases: list[str]
    #: 기본 정책이 어느 층에서 왔는지. 화면이 근거를 표시합니다.
    resolved_from: ResolvedFrom
    #: VK 허용 목록으로 좁혀졌는지.
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

    # INACTIVE alias 는 어느 층에 있든 제외합니다. 카탈로그 상태가 최종 관문입니다.
    effective = base & active
    return AllowedModelResolution(
        aliases=sorted(effective), resolved_from=resolved_from, narrowed_by_key=narrowed
    )
