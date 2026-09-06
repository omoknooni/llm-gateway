"""FastAPI 앱 조립.

레이어 규칙은 backend/docs/00-admin-api-architecture.md 를 따릅니다.
router 는 도메인 규칙을 갖지 않고, 트랜잭션 경계는 service 가 소유합니다.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.auth import AdminJWTVerifier, load_admin_jwt_configs
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.config import get_settings
from app.core.db import create_engine, dispose_engine, get_session_factory, session_scope
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.oidc import OIDCVerifier
from app.core.redis_client import create_redis_client

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_runtime()

    create_engine()
    app.state.redis = create_redis_client()
    # 정책 캐시는 삭제만 합니다. 값은 gateway 가 채웁니다(AGENTS.md 캐시 소유권).
    app.state.cache_mgr = CacheInvalidationManager(app.state.redis, get_session_factory())

    # ── 관리자 인증 경로 ──
    # OIDC 가 1차 경로이고, Admin JWT 는 다중 IdP·자체 토큰을 수용하는 보조 경로입니다.
    if settings.OIDC_ISSUER_URL:
        app.state.oidc_verifier = OIDCVerifier(
            issuer_url=settings.OIDC_ISSUER_URL,
            audience=settings.OIDC_AUDIENCE,
            jwks_cache_ttl_seconds=settings.OIDC_JWKS_CACHE_TTL_SECONDS,
            discovery_url_override=settings.OIDC_DISCOVERY_URL_OVERRIDE,
        )
        logger.info("oidc.enabled", issuer=settings.OIDC_ISSUER_URL)
    else:
        app.state.oidc_verifier = None
        logger.info("oidc.disabled", reason="OIDC_ISSUER_URL 미설정")

    admin_jwt_verifier = AdminJWTVerifier()
    async with session_scope() as session:
        admin_jwt_verifier.load(await load_admin_jwt_configs(session))
    app.state.admin_jwt_verifier = admin_jwt_verifier

    if settings.DEV_LOGIN_ENABLED:
        logger.warning("auth.dev_login_enabled", hint="운영 환경에서는 반드시 꺼야 합니다")
    if not (settings.OIDC_ISSUER_URL or admin_jwt_verifier.enabled or settings.DEV_LOGIN_ENABLED):
        # 조용히 뜨면 모든 요청이 401 인 이유를 아무도 모릅니다.
        raise RuntimeError(
            "사용 가능한 관리자 인증 경로가 없습니다: OIDC_ISSUER_URL, auth.admin_jwt_configs, "
            "DEV_LOGIN_ENABLED 중 하나가 필요합니다"
        )

    logger.info("app.started", env=settings.APP_ENV)
    yield

    if app.state.oidc_verifier is not None:
        await app.state.oidc_verifier.aclose()
    await app.state.redis.aclose()
    await dispose_engine()
    logger.info("app.shutdown")


def _error_response(
    status_code: int, code: str, message: str, details: dict, request: Request
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": getattr(request.state, "request_id", ""),
            }
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.LOG_LEVEL, json_output=settings.APP_ENV != "development")

    app = FastAPI(
        title="llm-gateway Admin API",
        description="control plane. 팀/사용자/Virtual Key/모델 카탈로그/예산/rate limit 의 source of truth.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def bind_request_id(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if exc.status_code >= 500:
            logger.error("request.failed", code=exc.code, message=exc.message, exc_info=True)
        else:
            logger.info("request.rejected", code=exc.code, message=exc.message)
        return _error_response(exc.status_code, exc.code, exc.message, exc.details, request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # 내부 예외 타입을 노출하지 않습니다. 스택트레이스는 로그에만 남깁니다.
        logger.error("request.unhandled", error=str(exc), exc_info=True)
        return _error_response(500, "internal_error", "내부 오류가 발생했습니다", {}, request)

    from app.routers import (
        allowed_models,
        health,
        internal,
        models,
        service_tokens,
        teams,
        users,
    )

    app.include_router(health.router)

    # 도메인 라우터는 전부 버전 prefix 아래에 둡니다.
    api = APIRouter(prefix=settings.API_PREFIX)
    api.include_router(users.router)
    api.include_router(teams.router)
    api.include_router(models.router)
    api.include_router(allowed_models.router)
    api.include_router(service_tokens.router)
    api.include_router(internal.router)
    app.include_router(api)

    return app


app = create_app()
