"""사용량 집계·조회 규칙.

집계 축, 기간 경계, 지표 정의를 한곳에 둡니다. 같은 숫자를 대시보드와 리더보드가 다르게
계산하지 않게 하려는 것이 목적입니다
([leaderboard-and-dashboard.md](../../../docs/leaderboard-and-dashboard.md) —
"비용, 토큰, 호출 수는 동일 기간 조건에서 일관되게 계산되어야 합니다").

기간 경계는 예산과 **같은 UTC 기준**입니다(`app.policy.budget`). 경계가 갈리면 예산 화면의
소진액과 사용량 화면의 비용이 서로 맞지 않습니다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.policy.budget import period_bounds as period_bounds_utc

#: 월 경계는 예산과 **같은 함수**를 씁니다. 문장으로만 "같은 UTC 경계"라고 적으면 한쪽이
#: 바뀔 때 조용히 갈라집니다. 재수출해서 호출 지점이 하나가 되게 합니다.
__all__ = [
    "NO_USER_ID",
    "NO_USER_LABEL",
    "TrendGranularity",
    "UsageAxis",
    "UsageMetric",
    "aggregation_window",
    "failure_rate",
    "month_of",
    "months_in_range",
    "period_bounds_utc",
    "total_tokens",
    "utc_date",
    "weighted_average",
]

#: `usage_events.user_id` 가 NULL 인 행(= `TEAM` 소유 VK 호출)을 집계 테이블에 담을 때 쓰는 값.
#:
#: 집계 테이블의 `user_id` 는 PK 구성원이라 NULL 을 담을 수 없습니다(01 문서). 그래서 사람에
#: 귀속되지 않는 호출을 **예약 UUID 한 개**로 모읍니다. 07 문서 미결정 #5 를 여기서 종결합니다.
#: 사람 계정과 섞이지 않도록 nil UUID 를 쓰고, 사용자 축 조회는 이 값을 걸러냅니다.
NO_USER_ID = uuid.UUID(int=0)
NO_USER_LABEL = "(팀 공용 키)"


class UsageAxis(StrEnum):
    """리더보드·집계의 조회 축. 집계 테이블 PK 의 부분집합입니다."""

    TEAM = "TEAM"
    USER = "USER"
    MODEL = "MODEL"
    VIRTUAL_KEY = "VIRTUAL_KEY"


class UsageMetric(StrEnum):
    """정렬 기준. 세 축 전부 같은 기간 조건에서 계산합니다."""

    COST = "COST"
    REQUESTS = "REQUESTS"
    TOKENS = "TOKENS"


class TrendGranularity(StrEnum):
    DAY = "DAY"
    MONTH = "MONTH"


def utc_date(moment: datetime) -> date:
    """이벤트가 속한 **UTC 일자**. 로컬 날짜로 버킷을 나누면 월 집계와 경계가 어긋납니다."""
    return moment.astimezone(UTC).date()


def month_of(bucket: date) -> str:
    return bucket.strftime("%Y-%m")


def months_in_range(start: date, end: date) -> list[str]:
    """`[start, end]` 이 걸치는 월 목록(오름차순). 재집계 대상 월을 정하는 데 씁니다."""
    months: list[str] = []
    cursor = start.replace(day=1)
    last = end.replace(day=1)
    while cursor <= last:
        months.append(month_of(cursor))
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


def aggregation_window(now: datetime, lookback_days: int) -> tuple[date, date]:
    """재집계 구간 `[start, end]` (양끝 포함, UTC 일자).

    최신 버킷만 갱신하지 않고 며칠을 되돌아보는 이유는 **늦게 도착하는 이벤트** 때문입니다.
    gateway 는 usage 이벤트를 메모리에 스풀했다가 쓰므로(09 문서), 장애 복구 뒤 어제·그제
    타임스탬프의 행이 새로 들어올 수 있습니다. 집계가 멱등한 UPSERT 라서 다시 훑어도
    안전합니다.
    """
    today = utc_date(now)
    return today - timedelta(days=max(lookback_days, 0)), today


def total_tokens(input_tokens: int, output_tokens: int) -> int:
    """입출력만 셉니다. 캐시 토큰은 단가가 달라 합산하면 '토큰 수'의 의미가 흐려집니다."""
    return input_tokens + output_tokens


def failure_rate(request_count: int, error_count: int) -> Decimal:
    """실패율(%). 호출이 0 이면 0 입니다 — 0/0 을 100% 로 보이게 하지 않습니다."""
    if request_count <= 0:
        return Decimal("0.00")
    return (Decimal(error_count) / Decimal(request_count) * 100).quantize(Decimal("0.01"))


def weighted_average(pairs: list[tuple[int, int]]) -> int:
    """`(값, 가중치)` 의 가중 평균.

    일 집계의 평균 지연을 기간 전체로 합칠 때 씁니다. 단순 평균을 쓰면 호출이 3건인 날과
    3만 건인 날이 같은 무게를 갖습니다.
    """
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return 0
    return round(sum(value * weight for value, weight in pairs) / total_weight)
