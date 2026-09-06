"""Virtual Key 수명주기 작업.

만료 판정의 **진실의 원천은 gateway 의 요청 시점 검사**입니다. 이 작업은 표시 정합성을
맞추고 캐시를 정리합니다. 즉 이 작업이 늦게 돌아도 만료된 키가 인증되지는 않습니다.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.clock import utcnow
from app.models.enums import VKStatus
from app.repositories.virtual_key_repository import VirtualKeyRepository

logger = structlog.get_logger()

BATCH_SIZE = 500


async def expire_virtual_keys(session: AsyncSession, cache: CacheInvalidationManager) -> int:
    """만료 시각이 지난 키를 정리합니다.

    - `ACTIVE`  → `EXPIRED`
    - `ROTATED` → `REVOKED` (유예 종료. 로테이션은 유예를 expires_at 으로 표현합니다)
    """
    now = utcnow()
    repo = VirtualKeyRepository(session)
    candidates = await repo.list_expired_candidates(now=now, limit=BATCH_SIZE)
    if not candidates:
        return 0

    hashes: list[str] = []
    for key in candidates:
        if key.status == VKStatus.ROTATED:
            key.status = VKStatus.REVOKED
            key.revoked_at = now
            key.revoke_reason = "ROTATION_GRACE_ENDED"
            action = "CLOSE_ROTATED_VIRTUAL_KEY"
        else:
            key.status = VKStatus.EXPIRED
            action = "EXPIRE_VIRTUAL_KEY"

        hashes.append(key.key_hash)
        await audit.record_system(
            session,
            action=action,
            resource_type="virtual_key",
            resource_id=str(key.id),
            changes={"after": {"status": key.status.value, "key_prefix": key.key_prefix}},
        )

    await session.commit()
    await cache.invalidate(
        [cache_keys.vk_auth(item) for item in hashes], context={"source": "expire_virtual_keys"}
    )
    logger.info("job.expire_virtual_keys", processed=len(candidates))
    return len(candidates)
