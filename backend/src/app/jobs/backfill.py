"""사용량 집계 backfill.

주기 집계는 최근 구간만 봅니다(`USAGE_AGGREGATION_LOOKBACK_DAYS`). 그 창보다 오래된 원천은
정상 경로로는 **영원히** 집계되지 않습니다. 두 경우에 그런 이벤트가 생깁니다.

1. **M7 배포 시점** — gateway 는 M7 이전부터 `usage.usage_events` 를 직접 써 왔습니다.
   배포 순간 이미 창보다 오래된 이벤트가 쌓여 있습니다.
2. **창보다 긴 장애** — gateway 의 스풀은 메모리 기반이고, 지연 상한에 대한 계약이 없습니다.
   복구가 창보다 늦으면 그 이벤트들은 주기 집계가 훑는 구간 밖입니다.

주기 job 에 넣지 않고 별도 명령으로 둔 이유는, 전체 원천 재집계가 **사람이 시점을 정해
한 번 돌리는 작업**이기 때문입니다. 10분마다 전 구간을 훑으면 비용이 이벤트 수에 비례해
무한히 늘어납니다.

    # 원천에 있는 가장 이른 이벤트부터 오늘까지
    python -m app.jobs.backfill

    # 구간을 지정 (양끝 포함, UTC 일자)
    python -m app.jobs.backfill --since 2026-08-01 --until 2026-09-30

    # 무엇을 할지만 보기
    python -m app.jobs.backfill --dry-run

집계는 멱등한 UPSERT 라 몇 번을 돌려도 결과가 같습니다. 이미 집계된 구간을 다시 넣어도
수치가 두 배가 되지 않습니다.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

import structlog

from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.db import create_engine, dispose_engine, session_scope
from app.core.locks import advisory_lock
from app.core.logging import configure_logging
from app.jobs.usage_jobs import aggregate_usage_daily, aggregate_usage_monthly, earliest_event_date

logger = structlog.get_logger()

#: 한 번에 집계할 일수. 전 구간을 한 문장으로 처리하면 긴 트랜잭션이 주기 job 을 막습니다.
CHUNK_DAYS = 31


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


async def run_backfill(*, since: date | None, until: date | None, dry_run: bool) -> int:
    """구간을 조각내어 집계합니다. 처리한 일수를 돌려줍니다."""
    async with session_scope() as session:
        start = since or await earliest_event_date(session)
        if start is None:
            logger.info("backfill.no_events")
            return 0

        end = until or utcnow().date()
        if start > end:
            logger.warning("backfill.empty_range", since=start.isoformat(), until=end.isoformat())
            return 0

        total_days = (end - start).days + 1
        logger.info(
            "backfill.planned",
            since=start.isoformat(),
            until=end.isoformat(),
            days=total_days,
            chunks=-(-total_days // CHUNK_DAYS),
            dry_run=dry_run,
        )
        if dry_run:
            return total_days

    # 주기 집계와 동시에 돌면 같은 버킷을 두 트랜잭션이 UPSERT 합니다. 결과는 같지만
    # 교착 가능성이 있어 같은 잠금 아래에 둡니다.
    async with session_scope() as session, advisory_lock(session, "aggregate_usage_daily") as ok:
        if not ok:
            logger.warning("backfill.skipped_locked", reason="주기 집계가 실행 중입니다")
            return 0

        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
            daily = await aggregate_usage_daily(session, since=cursor, until=chunk_end)
            monthly = await aggregate_usage_monthly(session, since=cursor, until=chunk_end)
            logger.info(
                "backfill.chunk_done",
                since=cursor.isoformat(),
                until=chunk_end.isoformat(),
                daily_rows=daily,
                monthly_rows=monthly,
            )
            cursor = chunk_end + timedelta(days=1)

    logger.info("backfill.done", since=start.isoformat(), until=end.isoformat(), days=total_days)
    return total_days


async def main() -> None:
    parser = argparse.ArgumentParser(description="사용량 집계 backfill")
    parser.add_argument("--since", type=_parse_date, help="시작 일자(UTC, 포함). 기본값은 최초 이벤트")
    parser.add_argument("--until", type=_parse_date, help="종료 일자(UTC, 포함). 기본값은 오늘")
    parser.add_argument("--dry-run", action="store_true", help="구간만 계산하고 쓰지 않습니다")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_output=settings.APP_ENV != "development")
    settings.validate_runtime()

    create_engine()
    try:
        await run_backfill(since=args.since, until=args.until, dry_run=args.dry_run)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
