"""`/v1/messages` 의 경로와 순서 (docs/01, docs/04)."""

from __future__ import annotations

import json

from gateway.core.errors import ErrorCode, GatewayError
from tests.api.conftest import UNKNOWN_KEY, auth_header, body


def test_successful_call_returns_the_requested_alias(client):
    response = client.post("/v1/messages", headers=auth_header(), json=body())
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "claude-sonnet"
    assert payload["content"] == [{"type": "text", "text": "hello"}]
    assert payload["usage"]["input_tokens"] == 11
    assert "x-request-id" in response.headers


def test_provider_receives_the_gateway_end_user_id(client, adapter, auth_context):
    client.post("/v1/messages", headers=auth_header(), json=body(metadata={"user_id": "client-said"}))
    assert adapter.calls[0]["end_user_id"] == auth_context.user_id


def test_region_prefix_is_rewritten_for_the_model_region(client, adapter):
    client.post("/v1/messages", headers=auth_header(), json=body())
    # 카탈로그의 provider_model_id 는 apac. 접두사, region 은 ap-northeast-2 → 그대로.
    assert adapter.calls[0]["decision"].call_model_id.startswith("apac.")
    assert adapter.calls[0]["decision"].region == "ap-northeast-2"


# ── 거절 ──


def test_missing_credentials_is_401_in_anthropic_shape(client):
    response = client.post("/v1/messages", json=body())
    assert response.status_code == 401
    assert response.json() == {
        "type": "error",
        "error": {"type": "authentication_error", "message": "Invalid virtual key"},
    }


def test_unknown_key_is_rejected_before_the_router(client, adapter):
    response = client.post("/v1/messages", headers=auth_header(UNKNOWN_KEY), json=body())
    assert response.status_code == 401
    assert adapter.calls == []  # provider 까지 가지 않았습니다


def test_model_outside_the_key_scope_is_403(client, adapter):
    response = client.post("/v1/messages", headers=auth_header(), json=body(model="claude-opus"))
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "permission_error"
    assert adapter.calls == []


def test_unknown_model_is_404_not_403(client, adapter):
    """미등록과 권한 없음은 다른 사건입니다. 둘을 같은 답으로 뭉개면 원인을 못 찾습니다."""
    response = client.post("/v1/messages", headers=auth_header(), json=body(model="ghost"))
    # 캐시에도 DB 에도 없으므로 "확인할 수 없음"(503). DB 가 있으면 404 입니다.
    assert response.status_code == 503
    assert adapter.calls == []


def test_unsupported_field_names_the_field(client):
    response = client.post("/v1/messages", headers=auth_header(), json=body(seed=1))
    assert response.status_code == 400
    assert "'seed'" in response.json()["error"]["message"]


def test_dialect_mismatch_points_at_the_other_endpoint(client):
    """모델이 이 엔드포인트를 지원하지 않으면 대안을 알려줍니다."""
    response = client.post("/v1/messages", headers=auth_header(), json=body(model="openai-only"))
    assert response.status_code == 400
    assert "/v1/chat/completions" in response.json()["error"]["message"]


def test_scope_is_checked_before_the_dialect(client):
    """권한 없는 키는 어떻게 물어보든 같은 답을 받아야 합니다.

    방언 검사가 앞서면 권한 없는 키가 그 모델의 지원 방언을 알아낼 수 있습니다.
    """
    response = client.post("/v1/messages", headers=auth_header(), json=body(model="claude-opus"))
    assert response.status_code == 403
    assert "OPENAI_CHAT" not in response.json()["error"]["message"]


def test_provider_failure_maps_to_the_dialect_error_shape(client, adapter):
    adapter.error = GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed")
    response = client.post("/v1/messages", headers=auth_header(), json=body())
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"


def test_body_over_the_limit_is_413(client):
    huge = {"model": "claude-sonnet", "max_tokens": 8, "messages": [{"role": "user", "content": "x" * 40}]}
    client.app.state.settings.max_body_size = 10
    try:
        response = client.post("/v1/messages", headers=auth_header(), json=huge)
        assert response.status_code == 413
    finally:
        client.app.state.settings.max_body_size = 20 * 1024 * 1024


# ── 스트리밍 ──


def test_stream_emits_anthropic_frames_in_order(client):
    with client.stream("POST", "/v1/messages", headers=auth_header(), json=body(stream=True)) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())

    names = [line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert '"text":"hel"' in text


def test_stream_connect_failure_is_a_real_http_status(client, adapter):
    """스트림을 열어보지도 않고 200 을 주면 client 가 실패를 성공으로 처리합니다."""
    adapter.stream_error = GatewayError(ErrorCode.RATE_LIMIT_EXCEEDED, "throttled", retry_after=3)
    response = client.post("/v1/messages", headers=auth_header(), json=body(stream=True))
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3"


def test_streaming_unsupported_model_is_refused_before_calling(client, adapter):
    response = client.post(
        "/v1/messages", headers=auth_header(), json=body(model="no-stream", stream=True)
    )
    assert response.status_code == 400
    assert adapter.calls == []


def test_non_streaming_call_to_that_model_still_works(client, adapter):
    """스트리밍 미지원이 모델 자체를 막는 것은 아닙니다."""
    response = client.post("/v1/messages", headers=auth_header(), json=body(model="no-stream"))
    assert response.status_code == 200
    assert len(adapter.calls) == 1
