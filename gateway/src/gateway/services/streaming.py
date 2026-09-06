"""스트림 수명 관리.

세 가지를 봅니다.

- **idle timeout** — 청크 간 무응답 상한. 반드시 앞단 ALB 의 idle timeout 보다 작아야 합니다.
  크면 ALB 가 먼저 끊어 client 는 깔끔한 에러 대신 잘린 스트림을 봅니다.
- **usage 누적** — provider 는 usage 를 여러 이벤트에 나눠 줍니다(입력은 시작, 출력은 끝).
- **출력 텍스트 누적** — provider 가 usage 없이 끝났을 때 역산의 재료입니다. 0 으로 기록하면
  그 요청은 공짜가 됩니다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog

from gateway.core.normalized import (
    ContentDelta,
    MessageDelta,
    StreamEnd,
    StreamError,
    StreamEvent,
    StreamStart,
    TokenUsage,
)

logger = structlog.get_logger(__name__)

#: 스트림 안에서만 쓰는 오류 이름. HTTP 상태로는 말할 수 없는 자리입니다.
TIMEOUT_ERROR = "timeout_error"


class StreamAccumulator:
    """스트림이 흘러가는 동안 finalize 에 필요한 것을 모읍니다."""

    def __init__(self) -> None:
        self.usage = TokenUsage()
        self.stop_reason: str | None = None
        self.response_id: str | None = None
        self.text_length = 0
        self.failed = False

    def observe(self, event: StreamEvent) -> None:
        match event:
            case StreamStart():
                self.response_id = event.response_id
                self.usage.merge(event.usage)
            case ContentDelta():
                if event.text:
                    self.text_length += len(event.text)
            case MessageDelta():
                self.stop_reason = event.stop_reason
                self.usage.merge(event.usage)
            case StreamEnd():
                self.usage.merge(event.usage)
            case StreamError():
                self.failed = True


async def guard(
    events: AsyncIterator[StreamEvent], *, idle_timeout: float, accumulator: StreamAccumulator
) -> AsyncIterator[StreamEvent]:
    """idle timeout 을 적용하고 지나가는 이벤트를 누적기에 알립니다."""
    iterator = events.__aiter__()
    while True:
        try:
            event = await asyncio.wait_for(iterator.__anext__(), timeout=idle_timeout)
        except StopAsyncIteration:
            return
        except TimeoutError:
            logger.warning("stream.idle_timeout", seconds=idle_timeout)
            error = StreamError(
                code=TIMEOUT_ERROR, message="Upstream stopped sending data"
            )
            accumulator.observe(error)
            yield error
            return
        except Exception:
            # 스트림 도중의 예외는 이미 200 헤더가 나간 뒤라 HTTP 상태로 말할 수 없습니다.
            logger.exception("stream.failed")
            error = StreamError(code="api_error", message="Upstream stream failed")
            accumulator.observe(error)
            yield error
            return

        accumulator.observe(event)
        yield event
