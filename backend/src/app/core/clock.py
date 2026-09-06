"""시간. 애플리케이션은 timezone-aware UTC 만 다룹니다(01 문서 공통 규약).

naive datetime 이 섞이면 비교가 조용히 틀리므로, 현재 시각은 이 함수로만 얻습니다.
테스트에서 시간을 고정할 때도 여기 하나만 patch 합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def month_period(moment: datetime | None = None) -> str:
    """예산 기간 문자열 'YYYY-MM'. **UTC 기준 월**입니다(05 문서 / 08 문서 C3).

    표시만 KST 로 하고 저장·집행 경계는 UTC 입니다. 경계를 로컬 시간으로 두면 gateway 카운터,
    집계 배치, 대시보드가 각자 다른 월을 보게 됩니다.
    """
    moment = moment or utcnow()
    return moment.astimezone(UTC).strftime("%Y-%m")
