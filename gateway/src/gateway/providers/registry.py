"""provider 유형별 adapter 레지스트리.

라우터는 `registry.get(decision.provider)` 하나로 adapter 를 꺼냅니다. 라우터에 provider 별
`if` 가 생기면 provider 를 추가할 때마다 라우터를 고치게 됩니다.
"""

from __future__ import annotations

from gateway.core.errors import ErrorCode, GatewayError
from gateway.providers.base import ProviderAdapter


class ProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, provider: str, adapter: ProviderAdapter) -> None:
        self._adapters[provider] = adapter

    def get(self, provider: str) -> ProviderAdapter:
        adapter = self._adapters.get(provider)
        if adapter is None:
            # 카탈로그에는 있는데 gateway 가 그 provider 를 모르는 상태입니다. client 잘못이
            # 아니므로 5xx 로 답하고 로그에서 원인을 찾게 합니다.
            raise GatewayError(
                ErrorCode.PROVIDER_ERROR, f"No adapter registered for provider '{provider}'"
            )
        return adapter
