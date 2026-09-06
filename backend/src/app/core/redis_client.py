"""Redis 클라이언트.

backend 는 정책 캐시 키를 **삭제만** 하고 집행 카운터는 읽기만 합니다(08 문서 C2).
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import get_settings


def create_redis_client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_POOL_SIZE,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
