"""provider adapter 의 경계.

이 계층은 **방언을 모릅니다**. `NormalizedRequest` 를 받아 provider 의 wire 로 직렬화하고,
응답을 내부 표현으로 되돌립니다. adapter 안에 방언 타입이 등장하면 이 설계는 실패한 것입니다.

adapter 는 사용량을 기록하지 않습니다. `TokenUsage` 를 채워 돌려주기만 하고 기록은 라우터의
finalize 가 합니다 — 성공·실패·중단이 모두 한 자리를 지나야 누락이 없습니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from gateway.core.normalized import NormalizedRequest, ProviderResponse, StreamEvent
from gateway.core.routing import BackendDecision


class ProviderAdapter(ABC):
    @abstractmethod
    async def invoke(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> ProviderResponse: ...

    @abstractmethod
    async def invoke_stream(
        self, request: NormalizedRequest, decision: BackendDecision, *, end_user_id: str
    ) -> AsyncIterator[StreamEvent]:
        """**첫 이벤트를 내기 전에** 실패를 확정합니다.

        스트림을 열어보지도 않고 성공을 반환하면 upstream 4xx/5xx 가 "200 + 본문 속 에러"로
        둔갑해 client 가 실패를 성공으로 처리합니다. 연결 단계의 실패는 `GatewayError` 로
        올려 HTTP 상태로 답할 수 있게 합니다.
        """
        ...
