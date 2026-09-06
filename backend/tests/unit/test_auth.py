"""관리자 인증·인가 규칙 테스트."""

from __future__ import annotations

import base64
import json
import uuid

import pytest

from app.core.auth import (
    CurrentAdmin,
    _bootstrap_role,
    _claim_groups,
    _parse_dev_token,
    ensure_self_or_privileged,
    ensure_team_scope,
    extract_token,
    hash_token,
)
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, UnauthenticatedError
from app.models.enums import UserRole


class FakeRequest:
    def __init__(self, headers: dict | None = None, cookies: dict | None = None) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}


def _dev_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"dev.{body}.sig"


def test_hash_token_matches_shared_contract():
    """08 문서 C1: sha256(원문 UTF-8) 소문자 hex 64자. gateway 와 동일해야 합니다."""
    # 값을 고정합니다. 알고리즘이나 인코딩이 바뀌면 전 키가 인증 실패하므로 여기서 먼저 깨져야 합니다.
    assert hash_token("vk_live_abc") == "cb3d2968ced718b79c7c3e3017179cac05aaad22425f7c87edb73b355c8e79d9"


def test_extract_token_prefers_authorization_header():
    request = FakeRequest(headers={"Authorization": "Bearer abc"}, cookies={"admin_session": "cookie"})
    assert extract_token(request) == "abc"


def test_extract_token_falls_back_to_cookie():
    """frontend 는 SSR 에서 쿠키로 전달합니다."""
    assert extract_token(FakeRequest(cookies={"admin_session": "cookie"})) == "cookie"


def test_extract_token_missing_raises():
    with pytest.raises(UnauthenticatedError):
        extract_token(FakeRequest())


@pytest.mark.parametrize("token", ["notdev.x.y", "dev.only-two", "dev.!!!.sig"])
def test_parse_dev_token_rejects_malformed(token):
    assert _parse_dev_token(token) is None


def test_parse_dev_token_reads_payload():
    assert _parse_dev_token(_dev_token({"role": "ADMIN"})) == {"role": "ADMIN"}


def test_bootstrap_role_by_email_is_case_insensitive():
    settings = Settings(ADMIN_EMAILS="Admin@corp.example", ADMIN_GROUPS="")
    assert _bootstrap_role(settings, "admin@CORP.example", []) is UserRole.ADMIN


def test_bootstrap_role_by_group():
    settings = Settings(ADMIN_EMAILS="", ADMIN_GROUPS="platform-admins,sre")
    assert _bootstrap_role(settings, "someone@corp.example", ["sre"]) is UserRole.ADMIN


def test_bootstrap_role_absent_returns_none():
    """부트스트랩에 걸리지 않으면 DB 의 역할을 그대로 씁니다."""
    settings = Settings(ADMIN_EMAILS="", ADMIN_GROUPS="")
    assert _bootstrap_role(settings, "someone@corp.example", ["dev"]) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(["a", "b"], ["a", "b"]), ("a, b", ["a", "b"]), (None, []), ("", [])],
)
def test_claim_groups_accepts_list_or_csv(raw, expected):
    """IdP 마다 groups claim 이 배열이거나 콤마 문자열입니다."""
    assert _claim_groups({"groups": raw}, "groups") == expected


def _admin(role: UserRole, team_id: uuid.UUID | None = None) -> CurrentAdmin:
    return CurrentAdmin(user_id=uuid.uuid4(), email="a@b.c", role=role, team_id=team_id)


def test_team_scope_admin_passes_any_team():
    ensure_team_scope(_admin(UserRole.ADMIN), uuid.uuid4())


def test_team_scope_leader_passes_own_team():
    team_id = uuid.uuid4()
    ensure_team_scope(_admin(UserRole.TEAM_LEADER, team_id), team_id)


def test_team_scope_leader_forbidden_on_other_team():
    """다른 팀 리소스는 404 가 아니라 403 입니다(00 문서)."""
    with pytest.raises(ForbiddenError):
        ensure_team_scope(_admin(UserRole.TEAM_LEADER, uuid.uuid4()), uuid.uuid4())


def test_self_or_privileged():
    actor = _admin(UserRole.MEMBER)
    ensure_self_or_privileged(actor, actor.user_id)
    with pytest.raises(ForbiddenError):
        ensure_self_or_privileged(actor, uuid.uuid4())
