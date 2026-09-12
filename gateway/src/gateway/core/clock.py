"""시간.

공통 규약은 timezone-aware UTC 입니다. naive datetime 이 한 번이라도 섞이면 비교에서
TypeError 가 나거나, 더 나쁘게는 9시간 어긋난 값이 집계에 들어갑니다.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def month_period(now: datetime | None = None) -> str:
    """예산 기간 문자열 `YYYY-MM` (**UTC 기준**).

    사내 사용자는 KST 로 보지만 경계를 로컬 시간으로 두면 gateway 의 카운터 키와 backend 의
    집계 배치가 서로 다른 달을 가리킵니다. 저장은 UTC, 표시만 KST 입니다
    (backend 05 의 Period Definition).
    """
    return (now or utcnow()).strftime("%Y-%m")


def epoch_minute(now: float | None = None) -> int:
    """rate limit 고정 윈도의 식별자.

    벽시계를 씁니다 — `time.monotonic()` 은 프로세스마다 원점이 달라 여러 pod 이 같은 윈도를
    공유할 수 없습니다. NTP 보정으로 몇 초 흔들려도 분 단위 윈도에서는 무해합니다.
    """
    return int((now if now is not None else time.time()) // 60)
