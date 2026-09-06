"""모델 카탈로그 점검."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.repositories.model_repository import ModelPricingRepository

logger = structlog.get_logger()


async def check_missing_pricing(session: AsyncSession) -> list[str]:
    """ACTIVE 인데 현재 유효 단가가 없는 alias 를 경고합니다.

    단가가 없으면 비용이 0 으로 집계되어 관제 목적이 조용히 무너집니다.
    자동으로 고치지 않고 사람이 보게 합니다.
    """
    aliases = await ModelPricingRepository(session).aliases_without_current_pricing(at=utcnow())
    if aliases:
        logger.warning("job.models_missing_pricing", aliases=aliases, count=len(aliases))
    return aliases
