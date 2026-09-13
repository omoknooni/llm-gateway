"""rate limit API 스키마.

한도는 정수입니다 — 금액이 아니라 개수라서 문자열로 내보낼 이유가 없습니다.
`null` 과 **부재**의 의미가 다르므로(아래) 요청 모델에서 그 구분을 잃지 않게 다룹니다.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import RateLimitScope
from app.policy.rate_limit import LIMIT_FIELDS


class RateLimitSetRequest(BaseModel):
    """한도 upsert.

    세 한도는 독립이고 `null` 은 **"이 층에서 정의하지 않음"** 입니다(상위로 폴백).
    행 자체를 없애려면 `DELETE` 를 씁니다 — `null` 저장과 삭제는 의미가 다릅니다(06 문서).

    `0` 은 받지 않습니다. "전면 차단"을 뜻하게 되는데, 차단이 필요하면 VK 를 폐기하거나
    사용자를 비활성화하는 것이 맞습니다. 한도 0 은 원인을 찾기 어려운 형태의 차단입니다.
    """

    rpm_limit: int | None = Field(default=None, gt=0, description="분당 요청 수")
    tpm_limit: int | None = Field(default=None, gt=0, description="분당 토큰 수")
    concurrency_limit: int | None = Field(default=None, gt=0, description="동시 진행 요청 수")

    @model_validator(mode="after")
    def _not_all_null(self):
        """세 한도가 모두 비면 행 삭제와 구분되지 않습니다."""
        if all(getattr(self, field) is None for field in LIMIT_FIELDS):
            raise ValueError(
                "rpm_limit, tpm_limit, concurrency_limit 중 하나 이상이 필요합니다. "
                "정의를 지우려면 DELETE 를 쓰세요"
            )
        return self


class RateLimitResponse(BaseModel):
    id: str
    scope: RateLimitScope
    #: `GLOBAL` 은 대상이 없으므로 null 입니다.
    scope_id: str | None
    #: null 이면 그 scope 의 **모든 모델**에 적용됩니다.
    model_alias: str | None
    rpm_limit: int | None
    tpm_limit: int | None
    concurrency_limit: int | None
    #: 상위 scope 의 유효 한도를 넘는 설정인지. ADMIN 만 만들 수 있고 화면은 배지를 답니다.
    #: **null 은 "계산하지 않음"** 입니다 — 목록 조회는 행마다 상위를 해석하지 않습니다.
    #: 배지가 필요한 화면은 `/rate-limits/tree` 나 `/rate-limits/effective` 를 씁니다.
    exceeds_parent: bool | None = None
    created_at: datetime
    updated_at: datetime


class RateLimitListResponse(BaseModel):
    items: list[RateLimitResponse]


class ResolvedLimitResponse(BaseModel):
    value: int | None = None
    #: 어느 층에서 왔는지. `TEAM`, `USER:model` 처럼 표기합니다. 값이 없으면 null 입니다.
    resolved_from: str | None = None
    config_id: str | None = None


class EffectiveLimitsResponse(BaseModel):
    """해석 결과.

    두 축을 **따로** 돌려줍니다. `GLOBAL` 은 주체 한도와 별개로 항상 함께 집행되므로
    한 덩어리로 합치면 "왜 막혔는가"를 화면이 설명할 수 없습니다.
    """

    subject: dict[str, str | None]
    effective_limits: dict[str, ResolvedLimitResponse]
    global_limits: dict[str, ResolvedLimitResponse]


class RateLimitTreeMember(BaseModel):
    user_id: str
    display_name: str
    #: 이 사용자에게 **직접** 걸린 설정. 없으면 팀 값을 상속합니다.
    own: RateLimitResponse | None = None
    effective_limits: dict[str, ResolvedLimitResponse]


class RateLimitTreeResponse(BaseModel):
    team_id: str
    team_name: str
    team_limits: RateLimitResponse | None = None
    members: list[RateLimitTreeMember]


class ConflictingChild(BaseModel):
    scope_id: str
    #: 한도 종류별 `{child, parent}`. 운영자가 무엇을 정리해야 하는지 보이게 합니다.
    exceeds: dict[str, dict[str, int]]


class RateLimitSetResponse(BaseModel):
    config: RateLimitResponse
    #: 새 상위 한도보다 큰 하위 설정. **거절하지 않고 알립니다**(06 문서).
    #: 연쇄 자동 조정은 관리자가 의도하지 않은 값 변경을 만듭니다.
    conflicting_children: list[ConflictingChild] = Field(default_factory=list)


class RateLimitUsageEntry(BaseModel):
    scope: RateLimitScope
    scope_id: str | None
    model_alias: str | None
    limit_value: int | None
    current_value: int | None = None
    usage_pct: float | None = None


class RateLimitUsageResponse(BaseModel):
    """실시간 사용률. **best-effort** 입니다.

    카운터는 gateway 의 런타임 상태이고 backend 는 읽기만 합니다. 읽지 못하는 것은 오류가
    아니라 정상 상태 중 하나이므로, 관측이 안 된다고 설정 화면이 멈추면 안 됩니다(06 문서).
    """

    available: bool
    reason: str | None = None
    entries: list[RateLimitUsageEntry] = Field(default_factory=list)
