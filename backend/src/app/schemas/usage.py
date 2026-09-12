"""사용량 조회 스키마.

금액과 비율은 문자열입니다(00 문서 공통 타입 규약). 토큰·호출 수는 정수이고 JSON number
로 나갑니다 — 정밀도 문제가 없고, 프론트가 합산·정렬에 바로 쓰기 때문입니다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.policy.usage import TrendGranularity, UsageAxis, UsageMetric
from app.schemas.common import DecimalStr


class UsageTotals(BaseModel):
    """한 조회 범위의 합계. 모든 화면이 같은 정의를 씁니다."""

    request_count: int
    success_count: int
    error_count: int
    input_tokens: int
    output_tokens: int
    #: 입력 + 출력. 캐시 토큰은 단가가 달라 합산하지 않습니다.
    total_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: DecimalStr
    #: 실패 호출 비율(%). 프론트가 나눗셈을 중복 구현하지 않게 backend 가 계산합니다.
    failure_rate_pct: DecimalStr
    #: 호출 수로 가중한 평균. **p95 는 싣지 않습니다** — 버킷 간 합성이 불가능합니다.
    avg_latency_ms: int


class LeaderboardEntry(BaseModel):
    #: 축의 식별자. TEAM/USER/VIRTUAL_KEY 는 UUID 문자열, MODEL 은 alias 입니다.
    key: str
    #: 표시용 이름. 삭제된 대상이거나 이름이 없으면 null 입니다.
    name: str | None = None
    totals: UsageTotals


class LeaderboardResponse(BaseModel):
    axis: UsageAxis
    metric: UsageMetric
    from_date: date
    to_date: date
    items: list[LeaderboardEntry]


class UsageOverviewResponse(BaseModel):
    """대시보드 overview. leaderboard-and-dashboard.md 의 최소 지표를 한 번에 담습니다."""

    from_date: date
    to_date: date
    totals: UsageTotals
    top_teams: list[LeaderboardEntry]
    top_users: list[LeaderboardEntry]
    top_models: list[LeaderboardEntry]


class UsageTrendPoint(BaseModel):
    #: `YYYY-MM-DD`(일) 또는 `YYYY-MM`(월).
    bucket: str
    totals: UsageTotals


class UsageTrendResponse(BaseModel):
    granularity: TrendGranularity
    from_date: date
    to_date: date
    points: list[UsageTrendPoint]


class AuthEventSummaryItem(BaseModel):
    #: 거절 사유. 값 집합의 소유자는 gateway 입니다(09 문서).
    outcome: str
    #: **묶음 창을 펼친 실제 실패 수.** 행 수가 아닙니다.
    occurrence_count: int
    #: 기록된 행 수. 창 묶음 때문에 실패 수보다 작습니다. 진단용으로만 씁니다.
    event_rows: int


class AuthEventSummaryResponse(BaseModel):
    from_date: date
    to_date: date
    total_occurrences: int
    items: list[AuthEventSummaryItem]
