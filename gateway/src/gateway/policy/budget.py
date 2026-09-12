"""예산 초과 판정.

**공유 계약** — backend 05 의 판정 순서를 그대로 구현합니다.

    1) 사용자 예산이 설정돼 있으면 → 사용자 소진 ≥ 사용자 한도 → 정책 적용
    2) 팀 예산이 설정돼 있으면     → 팀 소진   ≥ 팀 한도       → 정책 적용
    3) 둘 다 미설정                 → 통과

두 층을 **동시에** 봅니다. 사용자 예산이 남아도 팀 예산이 소진되면 차단입니다 — 하위가
상위를 우회할 수 있으면 상위 한도는 장식입니다.

I/O 가 없는 순수 판정만 둡니다. 조회·캐시·카운터는 `services/budget_service` 의 몫입니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

HARD_BLOCK = "HARD_BLOCK"
SOFT_WARN = "SOFT_WARN"


@dataclass(frozen=True)
class BudgetState:
    """한 층의 설정과 소진. 설정이 없으면 이 객체 자체를 만들지 않습니다."""

    scope: str
    scope_id: str
    limit_usd: Decimal
    policy: str
    used_usd: Decimal

    @property
    def exceeded(self) -> bool:
        """`>=` 입니다. 한도를 **정확히** 채운 상태도 초과로 봅니다.

        `limit_usd = 0` 은 "쓸 수 없음"이고 무제한이 아닙니다(backend 05). `>` 로 두면
        한도 0 이 사실상 무제한이 되어 의미가 뒤집힙니다.
        """
        return self.used_usd >= self.limit_usd


@dataclass(frozen=True)
class BudgetVerdict:
    #: 차단 사유가 된 층. None 이면 통과입니다.
    blocked_by: BudgetState | None
    #: 초과했지만 SOFT_WARN 이라 통과시킨 층들.
    warnings: tuple[BudgetState, ...]

    @property
    def blocked(self) -> bool:
        return self.blocked_by is not None


def evaluate(*states: BudgetState | None) -> BudgetVerdict:
    """가장 구체적인 층부터 순서대로 넘깁니다(사용자 → 팀).

    초과한 층이 여럿이면 **먼저 온 HARD_BLOCK 이 차단 사유**가 됩니다. 사용자 한도로 막힌
    사람에게 팀 한도를 이유로 답하면 본인이 고칠 수 없는 것을 고치라는 말이 됩니다.
    """
    blocked_by: BudgetState | None = None
    warnings: list[BudgetState] = []

    for state in states:
        if state is None or not state.exceeded:
            continue
        if state.policy == HARD_BLOCK:
            if blocked_by is None:
                blocked_by = state
        else:
            warnings.append(state)

    return BudgetVerdict(blocked_by=blocked_by, warnings=tuple(warnings))
