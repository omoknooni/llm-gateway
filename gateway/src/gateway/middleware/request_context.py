"""요청 컨텍스트 미들웨어 (pure ASGI).

`request_id` 를 발급하고 타이머를 시작합니다. 스택의 가장 바깥이라 여기서 잰 시간이
`usage_events.latency_ms` 가 됩니다.

**BaseHTTPMiddleware 를 쓰지 않습니다.** SSE 가 기본인 서비스에서 그 구현은 StreamingResponse 와
조합했을 때 스트림이 끊깁니다. 스택 전체가 pure ASGI 인 이유입니다.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gateway.core.context import STATE_REQUEST, RequestContext

#: client 가 이미 상관 id 를 들고 있으면 그것을 잇습니다. 없으면 새로 만듭니다.
_INCOMING_HEADER = b"x-request-id"


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        incoming = headers.get(_INCOMING_HEADER, b"").decode("latin-1").strip()
        # client 가 준 값은 신뢰하지 않고 길이만 제한해 그대로 잇습니다. UUID 를 강요하면
        # 사내 서비스의 기존 상관 id 체계를 끊게 됩니다.
        request_id = incoming[:128] or str(uuid.uuid4())

        ctx = RequestContext(request_id=request_id)
        state = scope.setdefault("state", {})
        state[STATE_REQUEST] = ctx

        structlog.contextvars.bind_contextvars(request_id=request_id, path=scope.get("path", ""))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers_out = message.setdefault("headers", [])
                headers_out.append((b"x-request-id", request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "path")
