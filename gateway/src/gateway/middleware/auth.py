"""VK 인증 미들웨어 (pure ASGI).

실패는 방언에 맞는 오류 본문으로 내보냅니다. 라우팅 전이라 경로로 방언을 정합니다.

거절 사유(`GatewayError.outcome`)는 여기서 로그로만 남기고, `usage.auth_events` 기록은
기록 계층이 붙을 때 이 자리에서 함께 호출합니다(M5).
"""

from __future__ import annotations

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from gateway.core.context import STATE_AUTH
from gateway.core.dialect import dialect_for_path
from gateway.core.errors import GatewayError
from gateway.dialects.errors import send_error

logger = structlog.get_logger(__name__)

#: 프로브는 인증 면제입니다. 인증이 필요하면 쿠버네티스가 자격 증명을 들고 있어야 합니다.
EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        app_state = scope["app"].state
        headers = dict(scope.get("headers", []))

        try:
            context = await app_state.auth_service.authenticate(
                authorization=headers.get(b"authorization", b"").decode("latin-1"),
                api_key=headers.get(b"x-api-key", b"").decode("latin-1"),
                redis=app_state.redis,
                session_factory=app_state.session_factory,
            )
        except GatewayError as err:
            logger.info("auth.rejected", path=path, outcome=err.outcome, code=err.code)
            await send_error(send, dialect_for_path(path), err)
            return

        scope.setdefault("state", {})[STATE_AUTH] = context
        structlog.contextvars.bind_contextvars(
            virtual_key_id=context.virtual_key_id,
            team_id=context.team_id,
            user_id=context.user_id,
        )

        # 사용 이력. 응답 경로를 막지 않도록 백그라운드로 보내고, 실패해도 무시합니다.
        tracker = app_state.last_used
        if tracker.should_write(context.virtual_key_id):
            app_state.background.spawn(
                tracker.write(app_state.session_factory, context.virtual_key_id),
                name="last_used",
            )

        await self.app(scope, receive, send)
