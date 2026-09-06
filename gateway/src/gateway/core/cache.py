"""정책 캐시 접근의 공통 규칙.

캐시는 **없어도 되는 것**입니다. 그래서 여기서는 어떤 실패도 예외로 올리지 않고 miss 로
바꿉니다 — 연결 오류든, 구버전 형식이든, 깨진 JSON 이든 결과는 같습니다: DB 에서 재구성.
항목 하나가 영구 500 이 되는 것을 막는 방어이기도 합니다.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def get_json(redis, key: str) -> Any | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
    except Exception as exc:
        logger.warning("cache.read_failed", key=key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("cache.parse_failed_treated_as_miss", key=key)
        return None


async def set_json(redis, key: str, value: Any, ttl: int) -> None:
    if redis is None:
        return
    try:
        await redis.setex(key, ttl, json.dumps(value, separators=(",", ":")))
    except Exception as exc:
        logger.warning("cache.write_failed", key=key, error=str(exc))
