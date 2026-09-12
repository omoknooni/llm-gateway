"""rate limit 해석.

> **공유 계약** — gateway 가 집행용으로 같은 규칙을 구현합니다(08 문서 C3). 규칙이 갈리면
> "화면에는 rpm 600 인데 실제로는 100 에서 막히는" 상태가 됩니다.

두 축입니다.

```text
(A) 주체 축: VIRTUAL_KEY > USER > TEAM 중 가장 구체적인 정의
(B) 전역 축: GLOBAL 정의 (모델별)
둘 다 통과해야 요청이 진행됩니다.
```

핵심은 **폴백이 한도 종류별로 독립**이라는 것입니다. `USER` 가 `tpm` 만 정의했다면 `rpm` 은
`TEAM` 에서 옵니다. 행 단위로 "가장 구체적인 행 하나"를 고르는 것이 아닙니다 — 그렇게 하면
부분 정의(rpm 만 설정)가 상위의 tpm 까지 지워 버립니다.

같은 한도 종류가 여러 층에 있을 때 **합산하거나 최소값을 취하지 않습니다.** 가장 구체적인
층 하나가 이깁니다. 최소값을 취하면 상위에 낮은 값을 두는 것만으로 하위 설정이 무의미해져,
운영자가 "왜 이 한도인가"를 설명할 수 없게 됩니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.models.enums import RateLimitScope

#: 한도 종류. 세 가지는 독립이고, 하나라도 걸리면 거절합니다.
LIMIT_FIELDS = ("rpm_limit", "tpm_limit", "concurrency_limit")

#: 주체 축의 구체성 순서(구체적 → 일반). GLOBAL 은 이 축에 들어가지 않습니다.
SUBJECT_SCOPES = (RateLimitScope.VIRTUAL_KEY, RateLimitScope.USER, RateLimitScope.TEAM)

_SCOPE_RANK = {scope: rank for rank, scope in enumerate(SUBJECT_SCOPES)}


class LimitField(StrEnum):
    RPM = "rpm_limit"
    TPM = "tpm_limit"
    CONCURRENCY = "concurrency_limit"


@dataclass(frozen=True)
class LimitCandidate:
    """해석에 필요한 것만 담은 설정 행.

    ORM 객체를 그대로 쓰지 않는 이유는 규칙을 DB 접근과 분리하기 위해서입니다 —
    테이블 주도 테스트가 세션 없이 돌아야 합니다.
    """

    config_id: uuid.UUID
    scope: RateLimitScope
    #: `model_alias` 가 있는 설정. 같은 scope 안에서 모델 지정이 더 구체적입니다.
    model_scoped: bool
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    concurrency_limit: int | None = None

    @property
    def label(self) -> str:
        """`resolved_from` 표시값. 화면이 "왜 이 한도인가"를 설명하는 재료입니다."""
        return f"{self.scope.value}:model" if self.model_scoped else self.scope.value

    def limit(self, field: str) -> int | None:
        return getattr(self, field)


@dataclass(frozen=True)
class ResolvedLimit:
    """한 한도 종류의 해석 결과. 값이 없으면 그 한도는 **집행되지 않습니다**."""

    value: int | None = None
    resolved_from: str | None = None
    config_id: str | None = None

    @property
    def defined(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Resolution:
    rpm_limit: ResolvedLimit
    tpm_limit: ResolvedLimit
    concurrency_limit: ResolvedLimit

    def of(self, field: str) -> ResolvedLimit:
        return getattr(self, field)

    @property
    def any_defined(self) -> bool:
        return any(self.of(field).defined for field in LIMIT_FIELDS)


def _specificity(candidate: LimitCandidate) -> tuple[int, int]:
    """정렬 키. 작을수록 구체적입니다.

    같은 scope 안에서는 모델 지정이 먼저입니다 — `USER(claude-sonnet-4)` 가 `USER(all)` 을
    이깁니다.
    """
    return _SCOPE_RANK.get(candidate.scope, len(SUBJECT_SCOPES)), 0 if candidate.model_scoped else 1


def order_candidates(candidates: list[LimitCandidate]) -> list[LimitCandidate]:
    return sorted(candidates, key=_specificity)


def resolve(candidates: list[LimitCandidate]) -> Resolution:
    """한도 종류별로 가장 구체적인 **정의**를 채택합니다.

    `NULL` 은 "이 층에서 정의하지 않음"이므로 다음 후보로 넘어갑니다. 행을 통째로 고르지
    않는 이유가 여기 있습니다.
    """
    ordered = order_candidates(candidates)
    resolved: dict[str, ResolvedLimit] = {}

    for field in LIMIT_FIELDS:
        resolved[field] = ResolvedLimit()
        for candidate in ordered:
            value = candidate.limit(field)
            if value is not None:
                resolved[field] = ResolvedLimit(
                    value=value, resolved_from=candidate.label, config_id=str(candidate.config_id)
                )
                break

    return Resolution(**resolved)


def split_axes(
    candidates: list[LimitCandidate],
) -> tuple[list[LimitCandidate], list[LimitCandidate]]:
    """`(주체 축, 전역 축)` 으로 나눕니다.

    `GLOBAL` 을 주체 축에 섞지 않습니다. 섞으면 팀 한도가 GLOBAL 보다 구체적이라는 이유로
    GLOBAL 이 덮여, 플랫폼 전체 상한이 사라집니다. 모든 팀 한도의 합이 Bedrock 쿼터를
    넘을 수 있으므로 GLOBAL 은 **항상 함께** 검사합니다.
    """
    subject = [c for c in candidates if c.scope in _SCOPE_RANK]
    global_axis = [c for c in candidates if c.scope == RateLimitScope.GLOBAL]
    return subject, global_axis


@dataclass(frozen=True)
class LimitViolation:
    """상위 한도를 넘은 한도 종류 하나."""

    field: str
    value: int
    parent_value: int
    parent_resolved_from: str


def check_within_parent(
    child: dict[str, int | None], parent: Resolution
) -> list[LimitViolation]:
    """하위 설정이 상위 유효 한도를 넘는지 봅니다.

    상위가 정의하지 않은 한도 종류는 비교 대상이 아닙니다 — 없는 상한을 넘을 수는 없습니다.
    ADMIN 은 이 제약을 받지 않으므로(06 문서), 호출자가 역할을 보고 위반을 거절할지
    표시만 할지 정합니다. 여기서는 **판단만 하고 예외를 던지지 않습니다.**
    """
    violations = []
    for field in LIMIT_FIELDS:
        value = child.get(field)
        limit = parent.of(field)
        if value is None or not limit.defined:
            continue
        if value > limit.value:
            violations.append(
                LimitViolation(
                    field=field,
                    value=value,
                    parent_value=limit.value,
                    parent_resolved_from=limit.resolved_from or "",
                )
            )
    return violations


def find_conflicting_children(
    parent: dict[str, int | None], children: list[tuple[str, dict[str, int | None]]]
) -> list[dict]:
    """새 상위 한도보다 큰 하위 설정을 찾습니다.

    **거절하지 않고 경고합니다**(06 문서). 연쇄 자동 조정은 관리자가 의도하지 않은 값 변경을
    만듭니다. 운영자가 목록을 보고 직접 정리하게 합니다.
    """
    conflicts = []
    for child_id, child_limits in children:
        exceeded = {
            field: {"child": child_limits[field], "parent": parent[field]}
            for field in LIMIT_FIELDS
            if child_limits.get(field) is not None
            and parent.get(field) is not None
            and child_limits[field] > parent[field]
        }
        if exceeded:
            conflicts.append({"scope_id": child_id, "exceeds": exceeded})
    return conflicts
