"""시간.

공통 규약은 timezone-aware UTC 입니다. naive datetime 이 한 번이라도 섞이면 비교에서
TypeError 가 나거나, 더 나쁘게는 9시간 어긋난 값이 집계에 들어갑니다.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
