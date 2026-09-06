"""정책 캐시 무효화.

원칙은 하나입니다. **control plane 은 지우기만 하고, 값은 gateway 가 채웁니다**(AGENTS.md).

순서도 계약입니다. 업무 트랜잭션을 **커밋한 뒤에** 삭제합니다. 먼저 지우면 커밋 사이에 들어온
gateway 요청이 옛 값을 다시 캐시에 채웁니다.

삭제 실패는 업무를 되돌리지 않습니다(이미 커밋됨). `audit.cache_invalidation_failures` 에
남기고 재시도합니다. 실패가 남아도 gateway 의 캐시 TTL 이 만료되면 최신 값을 읽으므로,
영향은 "정책 반영 지연"이지 "영구 불일치"가 아닙니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import utcnow
from app.models.audit import CacheInvalidationFailure

logger = structlog.get_logger()


@dataclass
class InvalidationResult:
    """무효화 결과. 라우터가 응답에 그대로 실어 운영자에게 반영 여부를 보여줍니다."""

    requested: int = 0
    deleted: int = 0
    failed_keys: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_keys


class CacheInvalidationManager:
    """정책 캐시 키를 삭제만 합니다.

    패턴(`SCAN`) 삭제 메서드를 **일부러 두지 않습니다.** 팬아웃 무효화는 DB 에서 대상 키
    목록을 만들어 정확히 삭제합니다. 키스페이스를 훑는 비용도 크고, 다른 plane 의 키를
    지울 위험이 있습니다(08 문서 C2).
    """

    def __init__(self, redis: aioredis.Redis, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._redis = redis
        self._session_factory = session_factory

    async def invalidate(
        self, keys: list[str], *, context: dict[str, Any] | None = None
    ) -> InvalidationResult:
        result = InvalidationResult(requested=len(keys))
        if not keys:
            return result

        try:
            deleted = await self._redis.delete(*keys)
            result.deleted = int(deleted or 0)
            logger.debug("cache.invalidated", key_count=len(keys), deleted=result.deleted)
        except Exception as exc:
            result.failed_keys = list(keys)
            logger.warning("cache.invalidation_failed", key_count=len(keys), error=str(exc))
            await self._record_failures(keys, context or {})

        return result

    async def retry_failed(self, *, limit: int = 500) -> int:
        """미해결 실패를 재시도합니다. 해결된 건수를 반환합니다."""
        resolved = 0
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CacheInvalidationFailure)
                    .where(CacheInvalidationFailure.resolved_at.is_(None))
                    .order_by(CacheInvalidationFailure.failed_at)
                    .limit(limit)
                )
            ).scalars().all()

            now = utcnow()
            for failure in rows:
                try:
                    await self._redis.delete(failure.cache_key)
                except Exception as exc:
                    failure.retry_count += 1
                    failure.last_retry_at = now
                    logger.warning(
                        "cache.retry_failed",
                        cache_key=failure.cache_key,
                        retry_count=failure.retry_count,
                        error=str(exc),
                    )
                    continue
                failure.resolved_at = now
                resolved += 1

            await session.commit()

        if resolved:
            logger.info("cache.retry_resolved", count=resolved)
        return resolved

    async def _record_failures(self, keys: list[str], context: dict[str, Any]) -> None:
        """실패를 **자체 세션**에 기록합니다.

        호출자의 업무 트랜잭션은 이미 커밋됐고, 여기서 그 세션을 다시 열면 커밋 책임이
        모호해집니다. 기록 자체가 실패해도 요청은 실패시키지 않습니다.
        """
        try:
            async with self._session_factory() as session:
                session.add_all(
                    [
                        CacheInvalidationFailure(
                            id=uuid.uuid4(),
                            cache_key=key,
                            failed_at=utcnow(),
                            context=context,
                        )
                        for key in keys
                    ]
                )
                await session.commit()
        except Exception as exc:
            # 기록마저 실패하면 남는 것은 로그뿐입니다. gateway 의 TTL 이 최후의 안전망입니다.
            logger.error("cache.failure_record_failed", key_count=len(keys), error=str(exc))
