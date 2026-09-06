"""운영용 내부 엔드포인트. 사람이 명시적으로 호출합니다."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.auth import RequireAdmin
from app.core.deps import CacheDep

router = APIRouter(prefix="/internal", tags=["Internal"])


@router.post("/cache/retry")
async def retry_cache_invalidation(actor: RequireAdmin, cache: CacheDep) -> dict[str, int]:
    """미해결 캐시 무효화 실패를 재시도합니다(00 문서 Cache Invalidation Contract)."""
    resolved = await cache.retry_failed()
    return {"resolved": resolved}
