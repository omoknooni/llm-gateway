"""docs/03 의 분류 규칙을 테이블 주도로 고정합니다."""

from __future__ import annotations

import pytest

from gateway.config import CLIENT_OTHER, Settings
from gateway.services.client_identifier import identify_client

REGISTERED = Settings().registered_client_set


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-llmgw-client": "codex"}, "codex"),
        ({"anthropic-client-platform": "desktop_app"}, "claude-desktop"),
        ({"user-agent": "Claude/1.2 Electron/33.0"}, "claude-desktop"),
        ({"user-agent": "claude-cli/2.0.1 (external)"}, "claude-code"),
        ({"originator": "codex_cli_rs"}, "codex"),
        ({"user-agent": "codex/1.0"}, "codex"),
        ({"user-agent": "OpenAI/Python 1.54.0"}, "openai-sdk"),
        ({"user-agent": "openai-node/4.68.0"}, "openai-sdk"),
        ({"user-agent": "curl/8.5.0"}, CLIENT_OTHER),
        ({}, CLIENT_OTHER),
    ],
)
def test_classification_table(headers: dict, expected: str):
    assert identify_client(headers, REGISTERED) == expected


def test_header_case_is_normalized():
    assert identify_client({"User-Agent": "claude-cli/2.0.1"}, REGISTERED) == "claude-code"


def test_desktop_wins_over_cli_prefix():
    """두 도구가 같은 'claude-cli/' 접두사를 씁니다. 순서가 뒤집히면 오분류됩니다."""
    headers = {"user-agent": "claude-cli/2.0.1", "anthropic-client-platform": "desktop_app"}
    assert identify_client(headers, REGISTERED) == "claude-desktop"


def test_unregistered_declared_value_falls_through_to_inference():
    headers = {"x-llmgw-client": "my-random-script", "user-agent": "claude-cli/2.0.1"}
    assert identify_client(headers, REGISTERED) == "claude-code"


def test_unregistered_declared_value_without_ua_is_other():
    assert identify_client({"x-llmgw-client": "my-random-script"}, REGISTERED) == CLIENT_OTHER


def test_inferred_value_must_also_be_registered():
    """설정에서 값을 빼면 그 분류가 꺼집니다. 카디널리티 상한이자 운영 손잡이입니다."""
    narrowed = Settings(registered_clients="claude-code").registered_client_set
    assert identify_client({"user-agent": "codex/1.0"}, narrowed) == CLIENT_OTHER
    assert identify_client({"user-agent": "claude-cli/2.0"}, narrowed) == "claude-code"


def test_result_is_always_within_known_values():
    """어떤 입력이 와도 계약 표(docs/03)를 벗어나지 않아야 합니다."""
    weird = [
        {"user-agent": "\x00\x01"},
        {"x-llmgw-client": "'; DROP TABLE usage_events; --"},
        {"originator": "codexxxxxx", "user-agent": "claude-cli/1"},
    ]
    for h in weird:
        assert identify_client(h, REGISTERED) in REGISTERED
