"""외부 의존성 없이 전체 스택(미들웨어 → 라우터 → adapter)을 지나는 테스트용 앱.

Redis 는 가짜, DB 는 없음(session_factory=None), provider 는 대역입니다. 그래서 여기서
검증되는 것은 **경로와 순서**입니다 — 미들웨어 순서, 거절 시점, 응답 형식.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from gateway.core import cache_keys
from gateway.core.context import AuthContext
from gateway.core.errors import GatewayError
from gateway.core.normalized import (
    ContentBlockStart,
    ContentBlockStop,
    ContentDelta,
    MessageDelta,
    ProviderResponse,
    StreamEnd,
    StreamStart,
    TextBlock,
    TokenUsage,
)
from gateway.main import create_app
from gateway.providers.base import ProviderAdapter
from gateway.providers.registry import ProviderRegistry
from gateway.services.auth_service import hash_key
from tests.fakes import FakeRedis
from tests.unit.test_model_config import make as make_model

warnings.filterwarnings("ignore", category=DeprecationWarning)

VALID_KEY = "vk_live_testkey"
UNKNOWN_KEY = "vk_live_unknown"


class FakeAdapter(ProviderAdapter):
    """호출된 인자를 기록하는 대역. 실패를 주입할 수도 있습니다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: GatewayError | None = None
        self.stream_error: GatewayError | None = None

    async def invoke(self, request, decision, *, end_user_id):
        self.calls.append({"request": request, "decision": decision, "end_user_id": end_user_id})
        if self.error:
            raise self.error
        return ProviderResponse(
            response_id="msg_fake",
            model_id=decision.call_model_id,
            content=[TextBlock(text="hello")],
            stop_reason="end_turn",
            usage=TokenUsage(input_tokens=11, output_tokens=3),
        )

    async def invoke_stream(self, request, decision, *, end_user_id) -> AsyncIterator:
        self.calls.append({"request": request, "decision": decision, "end_user_id": end_user_id})
        if self.stream_error:
            raise self.stream_error

        async def events():
            yield StreamStart(response_id="msg_fake", model_id=decision.call_model_id,
                              usage=TokenUsage(input_tokens=11))
            yield ContentBlockStart(index=0, block_type="text")
            yield ContentDelta(index=0, text="hel")
            yield ContentDelta(index=0, text="lo")
            yield ContentBlockStop(index=0)
            yield MessageDelta(stop_reason="end_turn", usage=TokenUsage(output_tokens=3))
            yield StreamEnd(usage=TokenUsage(input_tokens=11, output_tokens=3))

        return events()


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        virtual_key_id="11111111-1111-1111-1111-111111111111",
        owner_type="USER",
        owner_id="22222222-2222-2222-2222-222222222222",
        team_id="33333333-3333-3333-3333-333333333333",
        user_id="22222222-2222-2222-2222-222222222222",
        status="ACTIVE",
        expires_at=None,
        allowed_model_aliases=("claude-sonnet", "openai-only", "no-stream"),
    )


@pytest.fixture
def client(adapter, redis, auth_context) -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        # 캐시를 미리 채워 두면 DB 없이 인증과 모델 해석이 전부 통과합니다.
        portal = test_client.portal
        portal.call(redis.setex, cache_keys.vk_auth(hash_key(VALID_KEY)), 300, auth_context.to_json())
        # 미등록 키의 음성 캐시 — DB 없이도 "확인해 보니 무효"(401)를 재현합니다.
        portal.call(redis.setex, cache_keys.vk_miss(hash_key(UNKNOWN_KEY)), 30, "1")

        for model in (
            make_model(),
            make_model(alias="claude-opus"),                                  # 허용 목록 밖
            make_model(alias="openai-only", supported_dialects=("OPENAI_CHAT",)),
            make_model(alias="no-stream", supports_streaming=False),
        ):
            portal.call(
                redis.setex,
                cache_keys.model_policy(model.alias),
                300,
                json.dumps(model.to_dict()),
            )
        app.state.redis = redis
        app.state.session_factory = None  # DB 를 보면 안 되는 경로임을 강제합니다
        registry = ProviderRegistry()
        registry.register("BEDROCK", adapter)
        app.state.provider_registry = registry
        yield test_client


def auth_header(key: str = VALID_KEY) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


def body(**overrides) -> dict:
    return {
        "model": "claude-sonnet",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
        **overrides,
    }
