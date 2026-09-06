"""Mantle adapter 와 bearer broker (docs/05).

Bedrock native 와 다른 점(헤더 anthropic-version, 본문 model, non-200 처리)에 집중합니다.
"""

from __future__ import annotations

import json

import httpx
import pytest

from gateway.core.errors import ErrorCode, GatewayError
from gateway.providers.credentials import MantleCredentialBroker
from gateway.providers.mantle import MantleAdapter
from tests.unit.test_model_config import make as make_model
from tests.unit.test_provider_bedrock import decision as bedrock_decision
from tests.unit.test_provider_bedrock import request as make_request

ENDPOINT = "https://bedrock-mantle.ap-northeast-1.api.aws/anthropic"


def decision():
    model = make_model(
        alias="cowork-opus", provider="BEDROCK_MANTLE", endpoint_url=ENDPOINT
    )
    return bedrock_decision(model=model, provider="BEDROCK_MANTLE", endpoint_url=ENDPOINT)


class StubBroker(MantleCredentialBroker):
    def __init__(self) -> None:
        super().__init__()
        self.regions: list[str] = []

    async def bearer_token(self, region: str) -> str:
        self.regions.append(region)
        return f"token-for-{region}"


def adapter_for(handler) -> tuple[MantleAdapter, StubBroker]:
    broker = StubBroker()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MantleAdapter(client, broker), broker


async def test_request_shape_differs_from_bedrock_native():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "m", "content": [], "usage": {}})

    adapter, broker = adapter_for(handler)
    await adapter.invoke(make_request(), decision(), end_user_id="u-1")

    assert seen["url"] == f"{ENDPOINT}/v1/messages"
    # anthropic-version 은 헤더로, model 은 본문으로 갑니다.
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert "anthropic_version" not in seen["body"]
    assert seen["body"]["model"] == decision().call_model_id
    assert seen["headers"]["authorization"] == "Bearer token-for-ap-northeast-2"
    assert broker.regions == ["ap-northeast-2"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ErrorCode.INVALID_REQUEST),
        (401, ErrorCode.PROVIDER_ERROR),
        (403, ErrorCode.PROVIDER_ERROR),
        (404, ErrorCode.MODEL_INACTIVE),
        (429, ErrorCode.RATE_LIMIT_EXCEEDED),
        (500, ErrorCode.PROVIDER_ERROR),
        (504, ErrorCode.UPSTREAM_TIMEOUT),
    ],
)
async def test_http_status_mapping(status: int, expected: ErrorCode):
    adapter, _ = adapter_for(lambda request: httpx.Response(status, text="detail"))
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke(make_request(), decision(), end_user_id="u")
    assert exc.value.code is expected


async def test_auth_failures_are_ours_not_the_clients():
    """401/403 은 우리 토큰·IAM 문제입니다. client 키를 의심하게 만들면 안 됩니다."""
    adapter, _ = adapter_for(lambda request: httpx.Response(403, text="denied"))
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke(make_request(), decision(), end_user_id="u")
    assert exc.value.status == 502


async def test_stream_status_is_confirmed_before_yielding():
    """열어보지도 않고 성공을 반환하면 non-200 이 200 으로 둔갑합니다."""
    adapter, _ = adapter_for(lambda request: httpx.Response(429, text="slow down"))
    with pytest.raises(GatewayError) as exc:
        await adapter.invoke_stream(make_request(stream=True), decision(), end_user_id="u")
    assert exc.value.code is ErrorCode.RATE_LIMIT_EXCEEDED


async def test_stream_parses_sse_data_lines():
    frames = [
        'data: {"type":"message_start","message":{"id":"m","model":"x","usage":{"input_tokens":4}}}',
        "",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
        "",
        "data: [DONE]",
        "",
    ]
    adapter, _ = adapter_for(
        lambda request: httpx.Response(200, text="\n".join(frames))
    )
    events = await adapter.invoke_stream(make_request(stream=True), decision(), end_user_id="u")
    collected = [event async for event in events]
    assert len(collected) == 2  # [DONE] 은 이벤트가 아닙니다


async def test_missing_endpoint_is_refused_by_the_adapter_too():
    """모델 해석에서 이미 걸러지지만 adapter 가 자기 전제를 다시 확인합니다."""
    adapter, _ = adapter_for(lambda request: httpx.Response(200, json={}))
    broken = bedrock_decision(
        model=make_model(provider="BEDROCK_MANTLE", endpoint_url=None),
        provider="BEDROCK_MANTLE",
        endpoint_url=None,
    )
    with pytest.raises(GatewayError):
        await adapter.invoke(make_request(), broken, end_user_id="u")


# ── broker ──


async def test_bearer_is_cached_per_region():
    minted: list[str] = []

    def generator(credentials, region):
        minted.append(region)
        return f"tok-{region}"

    broker = MantleCredentialBroker(
        session_factory=lambda: _FakeSession(), token_generator=generator
    )
    assert await broker.bearer_token("ap-northeast-1") == "tok-ap-northeast-1"
    await broker.bearer_token("ap-northeast-1")
    await broker.bearer_token("us-east-2")
    # 리전이 다르면 다른 토큰입니다 — SigV4 가 리전 엔드포인트에 서명합니다.
    assert minted == ["ap-northeast-1", "us-east-2"]


async def test_bearer_expires_before_its_credentials():
    """자격 만료 직전에 만든 토큰이 곧바로 죽으면 매 요청이 401 이 됩니다."""
    from gateway.providers.credentials import ASSUMED_CREDENTIAL_TTL, CREDENTIAL_SKEW_SECONDS

    broker = MantleCredentialBroker(
        session_factory=lambda: _FakeSession(),
        token_generator=lambda c, r: "tok",
        now=lambda: 0.0,
    )
    await broker.bearer_token("us-east-1")
    cached = broker._cache[("in-account", "us-east-1")]
    assert cached.expires_at <= ASSUMED_CREDENTIAL_TTL - CREDENTIAL_SKEW_SECONDS


async def test_missing_credentials_fail_with_a_clear_message():
    broker = MantleCredentialBroker(
        session_factory=lambda: _FakeSession(credentials=None), token_generator=lambda c, r: "t"
    )
    with pytest.raises(RuntimeError, match="IRSA"):
        await broker.bearer_token("us-east-1")


def test_token_is_not_in_the_repr():
    from gateway.providers.credentials import _CachedBearer

    assert "secret" not in repr(_CachedBearer(token="secret", expires_at=1))


class _FakeSession:
    def __init__(self, credentials: object = object()) -> None:
        self._credentials = credentials

    def get_credentials(self):
        if self._credentials is None:
            return None
        return _FakeCredentials()


class _FakeCredentials:
    def get_frozen_credentials(self):
        return self
