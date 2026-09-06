"""client 식별 미들웨어 (pure ASGI).

Auth **앞**에 둡니다. 인증 실패 이벤트(`auth_events`)에도 client 를 남겨야 "어떤 도구가 잘못된
키로 오는지"를 볼 수 있기 때문입니다.

**절대 예외를 던지지 않습니다.** 어떤 오류가 나도 'other' 로 떨어지고 요청은 계속됩니다.
식별은 관측이지 게이트가 아닙니다(docs/03).
"""

from __future__ import annotations

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from gateway.config import CLIENT_OTHER
from gateway.core.context import STATE_CLIENT, STATE_REQUEST
from gateway.services.client_identifier import identify_client

logger = structlog.get_logger(__name__)


class ClientIdentificationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        client = CLIENT_OTHER
        try:
            headers = {
                k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])
            }
            client = identify_client(headers, scope["app"].state.settings.registered_client_set)
        except Exception as exc:
            logger.warning("client.identification_failed", error=str(exc))

        state[STATE_CLIENT] = client
        ctx = state.get(STATE_REQUEST)
        if ctx is not None:
            ctx.client = client
        structlog.contextvars.bind_contextvars(client=client)

        await self.app(scope, receive, send)
