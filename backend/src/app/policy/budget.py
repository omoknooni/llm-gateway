"""예산 판정 규칙.

> **공유 계약** — 기간 경계와 차단 판정 순서는 gateway 와 합의한 규칙입니다(05 문서).
> 규칙이 갈리면 "화면에는 여유인데 실제로는 차단"이 됩니다.

서비스가 아니라 여기에 두는 이유는 허용 모델 해석과 같습니다. 규칙을 DB 접근과 섞으면
테이블 주도 테스트를 쓸 수 없고, 같은 규칙이 조회 API 와 job 두 곳에 복제됩니다.

금액은 전부 `Decimal` 입니다. 소진율 계산에 float 를 쓰면 100.0% 경계가 99.99999% 가 됩니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

#: 금액 자릿수. `budget_configs.limit_usd` 와 `budget_usages.used_usd` 의 Numeric(14,4) 와 맞춥니다.
MONEY_QUANTUM = Decimal("0.0001")
#: 소진율 자릿수. 표시용이므로 2 자리면 충분합니다.
PCT_QUANTUM = Decimal("0.01")

DEFAULT_WARN_THRESHOLDS = [80, 90, 100]

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
#: API 파라미터에 그대로 쓰는 정규식. pydantic 이 1차로 걸러 줍니다.
PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class AlertLevel(StrEnum):
    """소진 경보 단계.

    프론트가 임계값 로직을 중복 구현하지 않도록 backend 가 계산해서 내려줍니다(05 문서).
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EXCEEDED = "EXCEEDED"


def is_valid_period(period: str) -> bool:
    return bool(_PERIOD_RE.match(period))


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """`YYYY-MM` → `[시작, 끝)` **UTC** 반개구간.

    `2026-09` 는 `2026-09-01T00:00:00Z` 이상 `2026-10-01T00:00:00Z` 미만입니다.
    저장과 집행 경계는 UTC 이고 KST 는 표시에만 씁니다(05 문서 Period Definition).
    KST 기준으로 경계를 잡으면 gateway 카운터 키와 집계 배치가 서로 다른 월을 보게 됩니다.
    """
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM)


def usage_pct(used: Decimal, limit: Decimal) -> Decimal:
    """소진율(%).

    한도 0 은 "쓸 수 없음"입니다. 0 으로 나누지 않고, 쓴 것이 있으면 100% 로 봅니다.
    한도 0 을 무제한으로 해석하면 상한이 장식이 됩니다 — 무제한은 **설정 없음**으로 표현합니다.
    """
    if limit <= 0:
        return Decimal("100.00") if used > 0 else Decimal("0.00")
    return (used / limit * 100).quantize(PCT_QUANTUM)


def remaining(used: Decimal, limit: Decimal) -> Decimal:
    """잔여액. 초과분은 음수로 그대로 둡니다.

    0 으로 깎으면 "얼마나 넘겼는가"가 화면에서 사라집니다. `SOFT_WARN` 은 초과한 채로
    계속 쌓이므로 그 값이 운영 판단의 재료입니다.
    """
    return quantize_money(limit - used)


def crossed_thresholds(used: Decimal, limit: Decimal, warn_thresholds: list[int]) -> list[int]:
    """도달한 임계값 목록(오름차순).

    job 이 이 결과와 `budget_usages.notified_thresholds` 의 차집합만 알립니다.
    """
    pct = usage_pct(used, limit)
    return sorted(t for t in set(warn_thresholds) if pct >= t)


def alert_level(used: Decimal, limit: Decimal, warn_thresholds: list[int] | None = None) -> AlertLevel:
    """경보 단계.

    ```text
    100% 이상                      → EXCEEDED
    100 미만 임계 중 가장 높은 것에 도달 → CRITICAL
    그보다 낮은 임계에 도달         → WARNING
    아무 임계에도 미달              → NORMAL
    ```

    기본값 `[80, 90, 100]` 에서는 80%→WARNING, 90%→CRITICAL, 100%→EXCEEDED 입니다.
    100 은 `EXCEEDED` 가 먼저 잡으므로 단계 판정에서는 쓰이지 않지만, 임계 **알림** 목록에는
    남아 있어야 합니다(초과 시점에도 알림이 한 번 나가야 하므로).
    """
    thresholds = warn_thresholds if warn_thresholds else DEFAULT_WARN_THRESHOLDS
    pct = usage_pct(used, limit)
    if pct >= 100:
        return AlertLevel.EXCEEDED

    below_full = sorted(t for t in set(thresholds) if t < 100)
    reached = [t for t in below_full if pct >= t]
    if not reached:
        return AlertLevel.NORMAL
    return AlertLevel.CRITICAL if reached[-1] == below_full[-1] else AlertLevel.WARNING


def counter_value(value: Decimal) -> str:
    """Redis 소진 카운터에 쓸 문자열.

    gateway 가 `INCRBYFLOAT` 로 누적하는 값이므로 **지수 표기를 내보내면 안 됩니다.**
    `Decimal("1E+2")` 를 그대로 쓰면 Redis 가 파싱에 실패하고 카운터가 통째로 깨집니다.
    """
    return format(quantize_money(value), "f")


@dataclass(frozen=True)
class AllocationCheck:
    """배분 검증 결과. 예외를 던지지 않고 값으로 돌려줍니다 — 서비스가 상태 코드를 정합니다."""

    allocated_usd: Decimal
    unallocated_usd: Decimal

    @property
    def exceeds(self) -> bool:
        return self.unallocated_usd < 0


def check_allocation(team_limit: Decimal, amounts: list[Decimal]) -> AllocationCheck:
    """배분 합계 검증.

    합계가 팀 한도를 넘으면 거절합니다. 넘지 않는 미달은 허용하고 여유분을 돌려줍니다
    (05 문서 Allocation). 하위 합이 상위를 넘을 수 있으면 팀 상한이 의미를 잃습니다.
    """
    allocated = quantize_money(sum(amounts, Decimal("0")))
    return AllocationCheck(allocated_usd=allocated, unallocated_usd=quantize_money(team_limit - allocated))
