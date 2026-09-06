"""`/v1/chat/completions` 와 `/v1/models`.

두 방언이 **같은 준비 경로**를 지나는지 확인합니다 — 인증·집행이 방언에 따라 갈리면
정책에 구멍이 생깁니다(ADR-0003).
"""

from __future__ import annotations

from gateway.core.errors import ErrorCode, GatewayError
from tests.api.conftest import UNKNOWN_KEY, auth_header


def chat(**overrides) -> dict:
    return {
        "model": "claude-sonnet",
        "messages": [{"role": "user", "content": "hi"}],
        **overrides,
    }


def test_successful_call(client):
    response = client.post("/v1/chat/completions", headers=auth_header(), json=chat())
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "claude-sonnet"
    assert payload["choices"][0]["message"]["content"] == "hello"
    assert payload["usage"]["prompt_tokens"] == 11


def test_authentication_error_uses_the_openai_shape(client):
    response = client.post("/v1/chat/completions", json=chat())
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert "type" not in response.json()  # Anthropic 의 최상위 type 이 아닙니다


def test_same_enforcement_as_the_other_dialect(client, adapter):
    """같은 키·같은 모델이면 방언과 무관하게 같은 판정이어야 합니다."""
    denied = client.post("/v1/chat/completions", headers=auth_header(), json=chat(model="claude-opus"))
    assert denied.status_code == 403
    assert denied.json()["error"]["type"] == "permission_error"

    unknown_key = client.post(
        "/v1/chat/completions", headers=auth_header(UNKNOWN_KEY), json=chat()
    )
    assert unknown_key.status_code == 401
    assert adapter.calls == []


def test_provider_receives_the_gateway_end_user_id(client, adapter, auth_context):
    client.post("/v1/chat/completions", headers=auth_header(), json=chat(user="client-said"))
    assert adapter.calls[0]["end_user_id"] == auth_context.user_id


def test_unsupported_field_is_named(client):
    response = client.post("/v1/chat/completions", headers=auth_header(), json=chat(seed=7))
    assert response.status_code == 400
    assert "'seed'" in response.json()["error"]["message"]


def test_provider_failure_maps_to_server_error(client, adapter):
    adapter.error = GatewayError(ErrorCode.PROVIDER_ERROR, "Upstream model call failed")
    response = client.post("/v1/chat/completions", headers=auth_header(), json=chat())
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "server_error"


def test_stream_frames(client):
    with client.stream(
        "POST", "/v1/chat/completions", headers=auth_header(), json=chat(stream=True)
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert text.rstrip().endswith("data: [DONE]")
    assert '"chat.completion.chunk"' in text
    assert '"content":"hel"' in text


def test_stream_usage_chunk_is_opt_in(client):
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers=auth_header(),
        json=chat(stream=True, stream_options={"include_usage": True}),
    ) as response:
        text = "".join(response.iter_text())
    assert '"usage"' in text and '"prompt_tokens":11' in text


# ── /v1/models ──


def test_model_list_is_filtered_by_the_key_scope(client, redis):
    """전체 카탈로그를 노출하면 client 는 쓸 수 없는 모델을 시도했다가 403 을 받습니다."""
    import json as _json

    from gateway.core import cache_keys

    client.portal.call(
        redis.setex,
        cache_keys.model_list(),
        300,
        _json.dumps(["claude-sonnet", "claude-opus", "openai-only", "no-stream"]),
    )
    response = client.get("/v1/models", headers=auth_header())
    ids = [m["id"] for m in response.json()["data"]]
    assert ids == ["claude-sonnet", "no-stream", "openai-only"]  # claude-opus 는 허용 목록 밖
    assert response.json()["object"] == "list"


def test_single_model_outside_the_scope_is_not_found(client):
    response = client.get("/v1/models/claude-opus", headers=auth_header())
    assert response.status_code == 404


def test_single_model_inside_the_scope(client):
    response = client.get("/v1/models/claude-sonnet", headers=auth_header())
    assert response.status_code == 200
    assert response.json()["id"] == "claude-sonnet"


def test_model_list_requires_authentication(client):
    assert client.get("/v1/models").status_code == 401
