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

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.api import anthropic, health, openai
from gateway.config import get_settings
from gateway.core.tasks import BackgroundTasks
from gateway.db import create_engine, create_session_factory
from gateway.logging import configure_logging
from gateway.middleware.auth import AuthMiddleware
from gateway.middleware.client_id import ClientIdentificationMiddleware
from gateway.middleware.request_context import RequestContextMiddleware
from gateway.providers.bedrock import BedrockAdapter
from gateway.providers.credentials import MantleCredentialBroker
from gateway.providers.mantle import MantleAdapter
from gateway.providers.registry import ProviderRegistry
from gateway.redis_client import create_redis
from gateway.services.auth_event_recorder import AuthEventRecorder
from gateway.services.auth_service import AuthService
from gateway.services.last_used import LastUsedTracker
from gateway.services.model_resolver import ModelResolver
from gateway.services.router import Router
from gateway.services.usage_recorder import UsageRecorder

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
    app.state.usage_recorder = UsageRecorder(settings.usage_spool_max)
    app.state.auth_events = AuthEventRecorder(settings.auth_event_window_seconds)
    resolver = ModelResolver(settings)
    app.state.model_resolver = resolver
    app.state.router = Router(settings, resolver)

    # Mantle 은 전 구간 async 라 httpx 클라이언트 하나를 공유합니다.
    mantle_http = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.mantle_connect_timeout,
            read=settings.stream_timeout,
            write=10,
            pool=30,
        )
    )
    app.state.mantle_http = mantle_http

    registry = ProviderRegistry()
    registry.register("BEDROCK", BedrockAdapter(settings))
    registry.register("BEDROCK_MANTLE", MantleAdapter(mantle_http, MantleCredentialBroker()))
    app.state.provider_registry = registry

    # 기동 시 의존성 연결을 확인하지 **않습니다.** Redis 나 DB 가 늦게 뜨는 상황에서 pod 가
    # 기동 실패로 재시작을 반복하면 복구가 더 느려집니다. 준비 여부는 /readyz 가 답합니다.
    flusher = asyncio.create_task(_flush_loop(app), name="record-flush")

    logger.info("gateway.started", env=settings.app_env, version=settings.app_version)
    try:
        yield
    finally:
        logger.info("gateway.shutting_down")
        flusher.cancel()
        with suppress(asyncio.CancelledError):
            await flusher
        # 진행 중인 기록(사용량, last_used_at)에 마지막 기회를 준 뒤 연결을 닫습니다.
        await app.state.background.drain()
        # 열린 창을 전부 비웁니다. 종료가 곧 감사 기록의 유실이 되면 안 됩니다.
        await app.state.auth_events.flush(app.state.session_factory, force=True)
        await app.state.usage_recorder.drain(app.state.session_factory)
        await mantle_http.aclose()
        await redis.aclose()
        await engine.dispose()


async def _flush_loop(app: FastAPI) -> None:
    """닫힌 거절 창을 쓰고, 스풀에 밀린 사용량 기록을 다시 시도합니다.

    사용량 기록은 요청마다 즉시 쓰므로 여기서 하는 일은 **DB 가 돌아왔을 때의 복구**뿐입니다.
    거절 기록은 창이 닫혀야 쓸 수 있어 이 주기가 곧 기록 지연 상한입니다.
    """
    interval = max(app.state.settings.auth_event_window_seconds, 1)
    while True:
        await asyncio.sleep(interval)
        try:
            await app.state.auth_events.flush(app.state.session_factory)
            await app.state.usage_recorder.drain(app.state.session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("record_flush.failed", error=str(exc))


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
    app.include_router(anthropic.router)
    app.include_router(openai.router)

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
