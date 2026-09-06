"""기록 위치가 문서의 표대로 갈리는지 (docs/01).

    provider 호출이 일어난 실패 → usage_events
    정책이 막은 거절           → auth_events
    요청 자체가 잘못됨         → 기록 없음
"""

from __future__ import annotations

from gateway.core.errors import ErrorCode, GatewayError
from tests.api.conftest import UNKNOWN_KEY, auth_header, body


def spooled(client):
    """DB 가 없으므로 기록은 전부 스풀로 갑니다 — 내용 확인에 그대로 씁니다."""
    client.portal.call(client.app.state.background.drain)
    return list(client.app.state.usage_recorder._spool)


def rejections(client):
    return client.app.state.auth_events.pop_expired(force=True)


def test_successful_call_is_recorded_with_cost_and_pricing_id(client):
    client.post("/v1/messages", headers=auth_header(), json=body())
    records = spooled(client)
    assert len(records) == 1
    record = records[0]
    assert record.status == "SUCCESS"
    assert record.dialect == "ANTHROPIC_MESSAGES"
    assert record.usage.input_tokens == 11
    assert record.pricing_id is not None
    assert record.estimated_cost_usd > 0
    assert record.client == "other"
    assert record.is_streaming is False


def test_client_tag_is_carried_into_the_record(client):
    client.post(
        "/v1/messages",
        headers={**auth_header(), "user-agent": "claude-cli/2.0.1"},
        json=body(),
    )
    assert spooled(client)[0].client == "claude-code"


def test_openai_dialect_is_recorded_as_such(client):
    client.post(
        "/v1/chat/completions",
        headers=auth_header(),
        json={"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert spooled(client)[0].dialect == "OPENAI_CHAT"


def test_provider_failure_is_recorded_as_error(client, adapter):
    """실패도 운영 관점에서는 중요한 신호입니다. 토큰이 0 이라도 행은 남깁니다."""
    adapter.error = GatewayError(ErrorCode.PROVIDER_ERROR, "boom")
    client.post("/v1/messages", headers=auth_header(), json=body())
    record = spooled(client)[0]
    assert record.status == "ERROR"
    assert record.error_code == "provider_error"
    assert record.estimated_cost_usd == 0


def test_upstream_timeout_is_recorded_as_timeout(client, adapter):
    adapter.error = GatewayError(ErrorCode.UPSTREAM_TIMEOUT, "slow")
    client.post("/v1/messages", headers=auth_header(), json=body())
    assert spooled(client)[0].status == "TIMEOUT"


def test_stream_is_recorded_after_the_last_frame(client):
    with client.stream("POST", "/v1/messages", headers=auth_header(), json=body(stream=True)) as response:
        "".join(response.iter_text())
    record = spooled(client)[0]
    assert record.is_streaming is True
    assert record.usage.output_tokens == 3
    assert record.ttft_ms is not None


# ── 거절 ──


def test_invalid_key_goes_to_auth_events_not_usage_events(client):
    client.post("/v1/messages", headers=auth_header(UNKNOWN_KEY), json=body())
    rows = rejections(client)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "INVALID_KEY"
    assert spooled(client) == []


def test_rejected_rows_carry_only_a_hash_prefix(client):
    """키 원문도 전체 해시도 싣지 않습니다. 8 hex 로는 원문을 복원할 수 없습니다."""
    client.post("/v1/messages", headers=auth_header(UNKNOWN_KEY), json=body())
    row = rejections(client)[0]
    assert row["key_hash_prefix"] is not None
    assert len(row["key_hash_prefix"]) == 8
    assert UNKNOWN_KEY not in str(row)


def test_model_not_allowed_is_recorded_with_the_subject(client):
    client.post("/v1/messages", headers=auth_header(), json=body(model="claude-opus"))
    row = rejections(client)[0]
    assert row["outcome"] == "MODEL_NOT_ALLOWED"
    assert row["model_alias"] == "claude-opus"
    assert row["virtual_key_id"] is not None
    assert spooled(client) == []


def test_malformed_request_is_not_recorded_anywhere(client):
    """client 버그 하나가 테이블을 채우면 안 됩니다."""
    client.post("/v1/messages", headers=auth_header(), json=body(seed=1))
    assert rejections(client) == []
    assert spooled(client) == []


def test_repeated_bad_keys_collapse_into_one_row(client):
    for _ in range(4):
        client.post("/v1/messages", headers=auth_header(UNKNOWN_KEY), json=body())
    rows = rejections(client)
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 4
