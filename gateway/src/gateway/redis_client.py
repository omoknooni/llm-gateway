"""Redis 연결.

타임아웃을 명시하는 것이 핵심입니다. 기본값(None)이면 느리거나 블랙홀이 된 노드 하나가
모든 awaited 호출을 무한 대기로 묶어 커넥션 풀을 고갈시킵니다. 캐시는 없어도 되는 것이므로
빨리 실패하고 DB 로 내려가는 편이 낫습니다(docs/README 실패 정책).
"""

from __future__ import annotations

import redis.asyncio as aioredis

from gateway.config import Settings


def create_redis(settings: Settings) -> aioredis.Redis:
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_connect_timeout,
        health_check_interval=settings.redis_health_check_interval,
    )
