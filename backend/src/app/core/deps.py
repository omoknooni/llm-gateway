"""라우터 공통 의존성."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request

from app.core.cache_invalidation import CacheInvalidationManager


@dataclass(frozen=True)
class RequestContext:
    """감사 로그에 남길 요청 메타데이터."""

    ip_address: str | None
    request_id: str


def get_request_context(request: Request) -> RequestContext:
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not client_ip and request.client is not None:
        client_ip = request.client.host
    return RequestContext(
        ip_address=client_ip or None,
        request_id=getattr(request.state, "request_id", ""),
    )


def get_cache_manager(request: Request) -> CacheInvalidationManager:
    return request.app.state.cache_mgr


def get_redis(request: Request) -> aioredis.Redis:
    """집행 카운터 **읽기** 용입니다.

    backend 가 이 클라이언트로 쓰는 곳은 예산 소진값 재시드 하나뿐이고, 그것이 예외임을
    05 문서가 못박습니다. 정책 캐시 삭제는 `CacheInvalidationManager` 를 지납니다.
    """
    return request.app.state.redis


CtxDep = Annotated[RequestContext, Depends(get_request_context)]
CacheDep = Annotated[CacheInvalidationManager, Depends(get_cache_manager)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
