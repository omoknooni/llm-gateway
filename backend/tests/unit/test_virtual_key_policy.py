"""Virtual Key 포맷과 상태 규칙 테스트.

gateway 가 같은 규칙으로 인증을 판정합니다(08 문서 C1). 한쪽만 바뀌면 전 키가 인증 실패하므로,
계약이 깨지면 여기가 먼저 빨개져야 합니다.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from app.core.auth import hash_token
from app.core.clock import utcnow
from app.models.enums import VKStatus
from app.policy.virtual_key import (
    LIVE_STATUSES,
    TERMINAL_STATUSES,
    can_authenticate,
    generate_key,
    is_transition_allowed,
    rotation_expiry,
)

KEY_PATTERN = re.compile(r"^vk_(live|dev)_[0-9A-Za-z]{20,}$")


def test_generated_key_matches_format():
    raw, prefix = generate_key("live")
    assert KEY_PATTERN.match(raw)
    assert raw.startswith(prefix)
    assert prefix == "vk_live_" + raw[len("vk_live_") :][:6]


def test_generated_keys_are_unique():
    keys = {generate_key("dev")[0] for _ in range(200)}
    assert len(keys) == 200


def test_key_hash_is_sha256_hex():
    raw, _ = generate_key("dev")
    digest = hash_token(raw)
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


# ── 인증 통과 조건 ──


@pytest.mark.parametrize("status", sorted(LIVE_STATUSES, key=str))
def test_live_statuses_authenticate_before_expiry(status):
    """ROTATED 도 유예 동안은 통과합니다. 유예는 expires_at 을 당겨 표현합니다."""
    assert can_authenticate(status, utcnow() + timedelta(hours=1), now=utcnow())


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=str))
def test_terminal_statuses_never_authenticate(status):
    assert not can_authenticate(status, utcnow() + timedelta(days=30), now=utcnow())


def test_expired_timestamp_blocks_even_when_active():
    assert not can_authenticate(VKStatus.ACTIVE, utcnow() - timedelta(seconds=1), now=utcnow())


def test_null_expiry_never_expires():
    """스키마는 NULL 을 허용하지만 API 로는 만들 수 없습니다(마이그레이션 유입 데이터용)."""
    assert can_authenticate(VKStatus.ACTIVE, None, now=utcnow())


# ── 상태 전이 ──


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (VKStatus.ACTIVE, VKStatus.ROTATED),
        (VKStatus.ACTIVE, VKStatus.REVOKED),
        (VKStatus.ACTIVE, VKStatus.EXPIRED),
        (VKStatus.ROTATED, VKStatus.REVOKED),
        (VKStatus.ROTATED, VKStatus.EXPIRED),
    ],
)
def test_allowed_transitions(current, target):
    assert is_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (VKStatus.REVOKED, VKStatus.ACTIVE),
        (VKStatus.EXPIRED, VKStatus.ACTIVE),
        (VKStatus.REVOKED, VKStatus.ROTATED),
        (VKStatus.ROTATED, VKStatus.ACTIVE),
        (VKStatus.ACTIVE, VKStatus.ACTIVE),
    ],
)
def test_forbidden_transitions(current, target):
    """폐기·만료는 되돌아가지 않습니다. 되살리려면 새 키를 발급합니다."""
    assert not is_transition_allowed(current, target)


# ── 로테이션 만료 ──


def test_rotation_does_not_extend_lifetime():
    """유예가 원래 만료보다 늦어도 원래 만료를 유지합니다."""
    now = utcnow()
    original = now + timedelta(hours=2)
    assert rotation_expiry(original, grace_until=now + timedelta(hours=24)) == original


def test_rotation_shortens_when_grace_is_earlier():
    now = utcnow()
    grace = now + timedelta(hours=1)
    assert rotation_expiry(now + timedelta(days=30), grace_until=grace) == grace


def test_rotation_of_never_expiring_key_uses_grace():
    now = utcnow()
    grace = now + timedelta(hours=6)
    assert rotation_expiry(None, grace_until=grace) == grace
