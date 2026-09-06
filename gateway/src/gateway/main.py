"""app factory 와 미들웨어 스택.

미들웨어 실행 순서(요청 처리 순):

    RequestContext → ClientIdentify → Auth → [Phase 4] Budget → RateLimit → router

Starlette 의 `add_middleware` 는 목록 앞에 삽입하므로 **마지막에 등록한 것이 가장 바깥**입니다.
즉 등록 순서는 실행 순서의 역순입니다. 순서가 계약인 지점이 있어 아래에 그대로 적어둡니다.

미들웨어는 `scope["app"].state` 로 Redis·세션 팩토리에 직접 접근합니다. 별도의 state 주입
미들웨어를 두지 않는 이유는, 그 방식이 등록 순서에 의존해 조용히 어긋나기 때문입니다.
`scope["app"]` 은 Starlette 이 미들웨어 진입 전에 채워 줍니다.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.api import health
from gateway.config import get_settings
from gateway.core.tasks import BackgroundTasks
from gateway.db import create_engine, create_session_factory
from gateway.logging import configure_logging
from gateway.middleware.auth import AuthMiddleware
from gateway.middleware.client_id import ClientIdentificationMiddleware
from gateway.middleware.request_context import RequestContextMiddleware
from gateway.redis_client import create_redis
from gateway.services.auth_service import AuthService
from gateway.services.last_used import LastUsedTracker

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)

    redis = create_redis(settings)
    engine = create_engine(settings)

    app.state.settings = settings
    app.state.redis = redis
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.background = BackgroundTasks()
    app.state.auth_service = AuthService(settings)
    app.state.last_used = LastUsedTracker(settings.last_used_throttle_seconds)

    # 기동 시 의존성 연결을 확인하지 **않습니다.** Redis 나 DB 가 늦게 뜨는 상황에서 pod 가
    # 기동 실패로 재시작을 반복하면 복구가 더 느려집니다. 준비 여부는 /readyz 가 답합니다.
    logger.info("gateway.started", env=settings.app_env, version=settings.app_version)
    try:
        yield
    finally:
        logger.info("gateway.shutting_down")
        # 진행 중인 기록(사용량, last_used_at)에 마지막 기회를 준 뒤 연결을 닫습니다.
        await app.state.background.drain()
        await redis.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="llm-gateway — data plane",
        version=get_settings().app_version,
        lifespan=lifespan,
        # client 에게 내부 스키마를 노출할 이유가 없습니다. 계약은 두 방언의 공개 스펙입니다.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # 등록 순서는 실행 순서의 역순입니다(마지막 등록 = 가장 바깥).
    app.add_middleware(AuthMiddleware)
    app.add_middleware(ClientIdentificationMiddleware)
    app.add_middleware(RequestContextMiddleware)  # 가장 바깥 = 가장 먼저 실행

    app.include_router(health.router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 원문은 로그에만 남깁니다. client 응답에 내부 사정을 싣지 않습니다.
        logger.exception("gateway.unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=json.loads(
                '{"error": {"type": "api_error", "message": "Internal server error"}}'
            ),
        )

    return app


app = create_app()
