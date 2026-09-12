"""예산 API 스키마.

금액은 전부 문자열로 나갑니다(`DecimalStr`). `usage_pct` 도 마찬가지입니다 — 소진율은
차단 판정의 근거라서 표시 단계에서 반올림이 달라지면 안 됩니다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import BudgetPeriod, BudgetPolicy, BudgetScope
from app.policy.budget import DEFAULT_WARN_THRESHOLDS, PERIOD_PATTERN, AlertLevel
from app.schemas.common import DecimalStr

#: DB 열이 `numeric(14,4)` 입니다. 입력에 같은 제약을 걸지 않으면 `0.00005` 같은 값이
#: PostgreSQL 에서는 반올림되고 Redis 카운터 문자열에서는 `Decimal.quantize()` 의
#: ROUND_HALF_EVEN 으로 잘려, **DB 내구 사본과 집행 카운터가 달라집니다.**
#: 표현할 수 없는 값은 저장 전에 422 로 거절합니다.
MONEY_DIGITS = {"max_digits": 14, "decimal_places": 4}

#: 소진값의 출처. 집행에 쓰이는 숫자(Redis)와 운영자가 보는 숫자를 같게 유지하되,
#: 어느 쪽을 봤는지 숨기지 않습니다(05 문서 "Redis와 DB의 불일치").
UsageSource = str


def _validate_thresholds(value: list[int]) -> list[int]:
    if not value:
        raise ValueError("warn_thresholds 는 비울 수 없습니다")
    if any(t <= 0 or t > 1000 for t in value):
        raise ValueError("warn_thresholds 는 1 이상 1000 이하의 % 값이어야 합니다")
    return sorted(set(value))


class BudgetSetRequest(BaseModel):
    """팀/사용자 예산 설정(upsert).

    한도 변경은 즉시 유효하고 당월 소진 누적에는 영향을 주지 않습니다(05 문서).
    """

    limit_usd: Decimal = Field(
        ge=0, **MONEY_DIGITS, description="월 상한 USD. 0 은 '쓸 수 없음'이고 무제한이 아닙니다"
    )
    policy: BudgetPolicy = BudgetPolicy.HARD_BLOCK
    period_type: BudgetPeriod = BudgetPeriod.MONTHLY
    warn_thresholds: list[int] = Field(default_factory=lambda: list(DEFAULT_WARN_THRESHOLDS))
    #: 미지정이면 오늘(UTC)부터입니다.
    effective_from: date | None = None

    _check_thresholds = field_validator("warn_thresholds")(_validate_thresholds)


class AllocationItem(BaseModel):
    user_id: uuid.UUID
    limit_usd: Decimal = Field(ge=0, **MONEY_DIGITS)


class AllocationSetRequest(BaseModel):
    """팀 예산의 멤버 배분.

    **전체 교체**입니다. 목록에 없는 멤버의 기존 배분은 해제됩니다. 부분 갱신으로 두면
    합계 검증이 "이번에 보낸 것"만 보게 되어 상한을 넘길 수 있습니다.
    """

    allocations: list[AllocationItem]
    policy: BudgetPolicy = BudgetPolicy.HARD_BLOCK
    warn_thresholds: list[int] = Field(default_factory=lambda: list(DEFAULT_WARN_THRESHOLDS))

    _check_thresholds = field_validator("warn_thresholds")(_validate_thresholds)

    @field_validator("allocations")
    @classmethod
    def _no_duplicate_users(cls, value: list[AllocationItem]) -> list[AllocationItem]:
        seen = {item.user_id for item in value}
        if len(seen) != len(value):
            raise ValueError("같은 사용자가 두 번 들어 있습니다")
        return value


class ReseedItem(BaseModel):
    scope: BudgetScope
    scope_id: uuid.UUID
    period: str = Field(pattern=PERIOD_PATTERN, description="UTC 기준 월. 'YYYY-MM'")
    used_usd: Decimal = Field(ge=0, **MONEY_DIGITS)


class ReseedRequest(BaseModel):
    """소진값 재시드. 운영 예외입니다(05 문서).

    control plane 이 집행 카운터를 쓰는 유일한 경로이므로 ADMIN 전용이고 감사에 남습니다.
    카운터 갱신에 실패하면 **전체가 취소되고 503** 입니다. 부분 적용은 없습니다.
    """

    items: list[ReseedItem] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=256, description="감사에 남습니다")

    @field_validator("items")
    @classmethod
    def _no_duplicate_targets(cls, value: list[ReseedItem]) -> list[ReseedItem]:
        """같은 (scope, scope_id, period) 가 두 번 오면 거절합니다.

        `budget_usages` 의 PK 이므로 한 요청에서 두 번 쓰면 커밋 시점에 충돌합니다.
        어느 값이 최종인지도 호출자 의도가 불분명합니다.
        """
        keys = {(item.scope, item.scope_id, item.period) for item in value}
        if len(keys) != len(value):
            raise ValueError("같은 대상·기간이 두 번 들어 있습니다")
        return value


# ── 응답 ──


class BudgetConfigResponse(BaseModel):
    id: str
    scope: BudgetScope
    scope_id: str
    limit_usd: DecimalStr
    period_type: BudgetPeriod
    policy: BudgetPolicy
    warn_thresholds: list[int]
    effective_from: date
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BudgetUsageItem(BaseModel):
    scope: BudgetScope
    scope_id: str
    name: str | None = None
    limit_usd: DecimalStr
    used_usd: DecimalStr
    remaining_usd: DecimalStr
    usage_pct: DecimalStr
    policy: BudgetPolicy
    alert_level: AlertLevel
    #: 'redis' | 'db'. 이 항목의 소진값을 어디서 읽었는지.
    source: UsageSource


class BudgetSummaryResponse(BaseModel):
    period: str
    #: 항목들의 출처 종합. 섞여 있으면 'mixed' 입니다 — 한쪽으로 뭉뚱그리면 거짓말이 됩니다.
    source: UsageSource
    items: list[BudgetUsageItem]


class AllocationEntry(BaseModel):
    user_id: str
    display_name: str
    email: str
    limit_usd: DecimalStr
    used_usd: DecimalStr
    usage_pct: DecimalStr
    alert_level: AlertLevel
    source: UsageSource


class AllocationResponse(BaseModel):
    team_id: str
    period: str
    team_limit_usd: DecimalStr
    allocated_usd: DecimalStr
    #: 팀 한도에서 배분하고 남은 여유분. 음수가 될 수 없습니다(초과는 409 로 거절).
    unallocated_usd: DecimalStr
    allocations: list[AllocationEntry]


class UsageBreakdownItem(BaseModel):
    key: str
    name: str | None = None
    cost_usd: DecimalStr
    request_count: int
    input_tokens: int
    output_tokens: int


class TeamBudgetUsageResponse(BaseModel):
    period: str
    budget: BudgetUsageItem
    by_member: list[UsageBreakdownItem]
    by_model: list[UsageBreakdownItem]


class UserBudgetUsageResponse(BaseModel):
    period: str
    budget: BudgetUsageItem
    by_model: list[UsageBreakdownItem]


class MyBudgetResponse(BaseModel):
    period: str
    #: 둘 다 null 이면 미설정 = 무제한입니다.
    user: BudgetUsageItem | None = None
    team: BudgetUsageItem | None = None


class UnsetBudgetTarget(BaseModel):
    id: str
    name: str
    team_id: str | None = None


class UnsetBudgetResponse(BaseModel):
    teams: list[UnsetBudgetTarget]
    users: list[UnsetBudgetTarget]


class ReseedResultItem(BaseModel):
    scope: BudgetScope
    scope_id: str
    period: str
    before_usd: DecimalStr | None
    after_usd: DecimalStr


class ReseedResponse(BaseModel):
    items: list[ReseedResultItem]
