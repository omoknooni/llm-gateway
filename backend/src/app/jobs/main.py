"""주기 작업 실행기.

API 프로세스와 같은 이미지, 다른 엔트리포인트로 실행합니다(Deployment 분리).

    python -m app.jobs.main
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as aioredis
import structlog

from app.core.cache_invalidation import CacheInvalidationManager
from app.core.config import get_settings
from app.core.db import create_engine, dispose_engine, get_session_factory, session_scope
from app.core.logging import configure_logging
from app.core.redis_client import create_redis_client
from app.jobs.budget_jobs import check_budget_thresholds, verify_budget_counters
from app.jobs.catalog_jobs import check_missing_pricing
from app.jobs.locks import advisory_lock
from app.jobs.usage_jobs import aggregate_usage_daily, aggregate_usage_monthly
from app.jobs.virtual_key_jobs import expire_virtual_keys

logger = structlog.get_logger()


@dataclass(frozen=True)
class Job:
    name: str
    interval_seconds: int
    run: Callable[..., Awaitable[object]]
    #: 두 번째 인자로 무엇을 받는지. 세션은 전부 받습니다.
    needs_cache: bool = False
    needs_redis: bool = False


JOBS: list[Job] = [
    Job("expire_virtual_keys", 300, expire_virtual_keys, needs_cache=True),
    Job("retry_cache_invalidation", 60, lambda session, cache: cache.retry_failed(), needs_cache=True),
    Job("check_missing_pricing", 3600, check_missing_pricing),
    # 예산 점검은 둘 다 집행 카운터를 **읽기만** 합니다(05 문서).
    Job("check_budget_thresholds", 600, check_budget_thresholds, needs_redis=True),
    Job("verify_budget_counters", 3600, verify_budget_counters, needs_redis=True),
    # 집계는 멱등해서(UPSERT) 실패하면 다음 주기에 그대로 다시 돌면 됩니다.
    # 일 집계가 월 집계보다 먼저 오도록 목록 순서를 맞춰 둡니다(동시 실행이라 보장은 아닙니다).
    Job("aggregate_usage_daily", 600, aggregate_usage_daily),
    Job("aggregate_usage_monthly", 3600, aggregate_usage_monthly),
]


async def _run_once(job: Job, cache: CacheInvalidationManager, redis: aioredis.Redis) -> None:
    async with session_scope() as session, advisory_lock(session, job.name) as acquired:
        if not acquired:
            logger.debug("job.skipped_locked", job=job.name)
            return
        if job.needs_cache:
            await job.run(session, cache)
        elif job.needs_redis:
            await job.run(session, redis)
        else:
            await job.run(session)


async def _loop(
    job: Job, cache: CacheInvalidationManager, redis: aioredis.Redis, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            await _run_once(job, cache, redis)
        except Exception as exc:  # 한 작업의 실패가 다른 작업을 멈추면 안 됩니다.
            logger.error("job.failed", job=job.name, error=str(exc), exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=job.interval_seconds)
        except TimeoutError:
            continue


async def run() -> None:
    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_output=settings.APP_ENV != "development")
    settings.validate_runtime()

    create_engine()
    redis = create_redis_client()
    cache = CacheInvalidationManager(redis, get_session_factory())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("jobs.started", jobs=[job.name for job in JOBS])
    await asyncio.gather(*(_loop(job, cache, redis, stop) for job in JOBS))

    await redis.aclose()
    await dispose_engine()
    logger.info("jobs.stopped")


if __name__ == "__main__":
    asyncio.run(run())
