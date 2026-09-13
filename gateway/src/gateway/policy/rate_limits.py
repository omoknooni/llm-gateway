"""rate limit 해석.

**공유 계약** — backend 06 의 두 축 해석입니다.

    (A) 주체 축: VIRTUAL_KEY(model) > VIRTUAL_KEY(*) > USER(model) > USER(*) > TEAM(model) > TEAM(*)
    (B) 전역 축: GLOBAL(model) > GLOBAL(*)
    둘 다 통과해야 요청이 진행됩니다.

핵심은 **한도 종류마다 따로 해석한다**는 것입니다. `NULL` 은 "정의되지 않음"이라 다음 후보로
넘어가므로, 한 요청에서 rpm 은 USER 층이 tpm 은 TEAM 층이 이길 수 있습니다. 그때 두 한도는
서로 다른 카운터를 씁니다 — **카운터는 이긴 설정의 scope 를 따라갑니다**(docs/08).
겹치는 층을 합산하거나 최소값을 취하지 않습니다. 가장 구체적인 층 하나가 이깁니다.

I/O 가 없는 순수 해석만 둡니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: 전체 모델 설정(`model_alias IS NULL`)의 카운터 자리표시자.
ALL_MODELS = "*"
#: GLOBAL 은 대상이 없으므로 scope_id 자리에 이 값을 씁니다.
GLOBAL_ID = "global"

RPM = "rpm"
TPM = "tpm"
CONCURRENCY = "concurrency"

LIMIT_TYPES = (RPM, TPM, CONCURRENCY)


@dataclass(frozen=True)
class LimitConfig:
    """`model.rate_limit_configs` 활성 행 하나."""

    scope: str
    scope_id: str | None
    model_alias: str | None
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    concurrency_limit: int | None = None

    def value_of(self, limit_type: str) -> int | None:
        return {
            RPM: self.rpm_limit,
            TPM: self.tpm_limit,
            CONCURRENCY: self.concurrency_limit,
        }[limit_type]

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "model_alias": self.model_alias,
            "rpm_limit": self.rpm_limit,
            "tpm_limit": self.tpm_limit,
            "concurrency_limit": self.concurrency_limit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LimitConfig:
        return cls(
            scope=data["scope"],
            scope_id=data.get("scope_id"),
            model_alias=data.get("model_alias"),
            rpm_limit=data.get("rpm_limit"),
            tpm_limit=data.get("tpm_limit"),
            concurrency_limit=data.get("concurrency_limit"),
        )


@dataclass(frozen=True)
class Limit:
    """채택된 한도 하나. 값과 **그 값이 어디서 왔는지**를 함께 들고 다닙니다.

    카운터 키가 이 세 값(`scope`, `scope_id`, `model_alias`)으로 만들어지므로, 값만 넘기면
    한도는 사용자 것인데 팀 단위로 세는 어긋남이 생깁니다.
    """

    limit_type: str
    value: int
    scope: str
    scope_id: str
    model_alias: str


@dataclass(frozen=True)
class EffectiveLimits:
    rpm: Limit | None = None
    tpm: Limit | None = None
    concurrency: Limit | None = None

    def __iter__(self):
        """정의된 한도만, 검사 순서대로 돌려줍니다(싼 것 → 되돌릴 필요가 있는 것)."""
        for limit in (self.rpm, self.tpm, self.concurrency):
            if limit is not None:
                yield limit

    @property
    def empty(self) -> bool:
        return self.rpm is None and self.tpm is None and self.concurrency is None


def resolve(candidates: Iterable[LimitConfig | None]) -> EffectiveLimits:
    """가장 구체적인 것부터 정렬된 후보에서 한도 종류별로 첫 정의를 채택합니다."""
    rows = [c for c in candidates if c is not None]
    picked: dict[str, Limit | None] = {}

    for limit_type in LIMIT_TYPES:
        picked[limit_type] = None
        for row in rows:
            value = row.value_of(limit_type)
            if value is None:
                continue
            picked[limit_type] = Limit(
                limit_type=limit_type,
                value=value,
                scope=row.scope,
                scope_id=row.scope_id or GLOBAL_ID,
                model_alias=row.model_alias or ALL_MODELS,
            )
            break

    return EffectiveLimits(
        rpm=picked[RPM], tpm=picked[TPM], concurrency=picked[CONCURRENCY]
    )
