"""팀/사용자 도메인 규칙 테스트.

02 문서에서 문장으로만 정해두면 구현이 갈리는 지점을 고정합니다.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.auth import CurrentAdmin
from app.core.clock import utcnow
from app.core.exceptions import ConflictError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.models.enums import UserRole
from app.services.user_service import UserService


class FakeUser:
    def __init__(self, *, role: UserRole, is_active: bool = True) -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.is_active = is_active


class FakeUserRepo:
    def __init__(self, other_active_admins: int) -> None:
        self._count = other_active_admins

    async def count_active_admins(self, *, excluding=None) -> int:
        return self._count


def _actor(user_id: uuid.UUID | None = None) -> CurrentAdmin:
    return CurrentAdmin(user_id=user_id or uuid.uuid4(), email="a@b.c", role=UserRole.ADMIN)


# ── cursor ──


def test_cursor_round_trip():
    moment, item_id = utcnow(), uuid.uuid4()
    assert decode_cursor(encode_cursor(moment, item_id)) == (moment, item_id)


def test_cursor_is_opaque_and_validated():
    """client 는 cursor 를 해석하지 않습니다. 깨진 값은 400 입니다."""
    with pytest.raises(ValidationError):
        decode_cursor("not-a-cursor!!")


# ── 마지막 ADMIN 보호 ──


async def test_last_admin_cannot_be_demoted():
    """관리자가 0명이 되면 복구 경로가 부트스트랩 재실행뿐입니다."""
    user = FakeUser(role=UserRole.ADMIN)
    with pytest.raises(ConflictError) as exc:
        await UserService._guard_last_admin(FakeUserRepo(0), user, becoming_admin=False)
    assert exc.value.code == "last_admin_protected"


async def test_admin_can_be_demoted_when_another_admin_exists():
    await UserService._guard_last_admin(FakeUserRepo(1), FakeUser(role=UserRole.ADMIN), becoming_admin=False)


async def test_guard_skipped_when_target_is_not_admin():
    await UserService._guard_last_admin(FakeUserRepo(0), FakeUser(role=UserRole.MEMBER), becoming_admin=False)


async def test_guard_skipped_when_promoting_to_admin():
    await UserService._guard_last_admin(FakeUserRepo(0), FakeUser(role=UserRole.ADMIN), becoming_admin=True)


# ── 자기 역할 변경 금지 ──


def test_cannot_change_own_role():
    actor = _actor()
    with pytest.raises(ConflictError) as exc:
        UserService._guard_self_role_change(actor, actor.user_id)
    assert exc.value.code == "cannot_modify_self_role"


def test_can_change_other_role():
    UserService._guard_self_role_change(_actor(), uuid.uuid4())


# ── 이메일 도메인 ──


def test_email_domain_allowed_list(monkeypatch):
    from app.core.config import Settings

    service = UserService(cache_mgr=None)
    monkeypatch.setattr(
        "app.services.user_service.get_settings",
        lambda: Settings(ALLOWED_EMAIL_DOMAINS="corp.example"),
    )
    service._check_email_domain("someone@corp.example")
    service._check_email_domain("someone@CORP.EXAMPLE")
    with pytest.raises(ValidationError):
        service._check_email_domain("someone@gmail.com")


def test_email_domain_unrestricted_when_unset(monkeypatch):
    from app.core.config import Settings

    service = UserService(cache_mgr=None)
    monkeypatch.setattr(
        "app.services.user_service.get_settings", lambda: Settings(ALLOWED_EMAIL_DOMAINS="")
    )
    service._check_email_domain("someone@anywhere.example")
