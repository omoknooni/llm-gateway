"""Virtual Key 의 포맷과 상태 규칙.

> **공유 계약** — 키 포맷, `key_hash` 산출식, 인증 통과 조건, 상태 전이는 gateway 와
> 동일해야 합니다(08 문서 C1). 한쪽만 바꾸면 전 키가 인증 실패합니다.

집행은 gateway 가 하지만, 판정 규칙 자체는 여기 순수 함수로 두고 테스트로 고정합니다.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from enum import StrEnum

from app.models.enums import VKStatus

#: 키 랜덤부의 엔트로피(바이트). 256비트.
KEY_RANDOM_BYTES = 32
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
#: 표시용 prefix 에 포함할 랜덤부 길이.
PREFIX_RANDOM_CHARS = 6

#: 인증을 통과할 수 있는 상태. ROTATED 는 유예 기간 동안만 살아 있고,
#: 유예는 `expires_at` 을 당겨 표현하므로 gateway 는 별도 유예 로직이 필요 없습니다.
LIVE_STATUSES = frozenset({VKStatus.ACTIVE, VKStatus.ROTATED})

#: 되돌아갈 수 없는 종료 상태.
TERMINAL_STATUSES = frozenset({VKStatus.REVOKED, VKStatus.EXPIRED})

_ALLOWED_TRANSITIONS: dict[VKStatus, frozenset[VKStatus]] = {
    VKStatus.ACTIVE: frozenset({VKStatus.ROTATED, VKStatus.REVOKED, VKStatus.EXPIRED}),
    VKStatus.ROTATED: frozenset({VKStatus.REVOKED, VKStatus.EXPIRED}),
    VKStatus.REVOKED: frozenset(),
    VKStatus.EXPIRED: frozenset(),
}


class RevokeReason(StrEnum):
    """폐기 사유. 감사 요구사항이 '폐기 사유와 수행 주체'를 요구하므로 필수입니다."""

    LOST = "LOST"
    OFFBOARDING = "OFFBOARDING"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    INCIDENT = "INCIDENT"
    ROTATION = "ROTATION"
    OTHER = "OTHER"


def _base62(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    if number == 0:
        return _BASE62[0]
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, 62)
        digits.append(_BASE62[remainder])
    return "".join(reversed(digits))


def generate_key(env: str) -> tuple[str, str]:
    """(원문, 표시용 prefix) 를 만듭니다.

    `env` 세그먼트(live/dev)는 환경 간 오배포를 눈으로 걸러내기 위한 것입니다.
    """
    random_part = _base62(secrets.token_bytes(KEY_RANDOM_BYTES))
    raw = f"vk_{env}_{random_part}"
    return raw, f"vk_{env}_{random_part[:PREFIX_RANDOM_CHARS]}"


def can_authenticate(status: VKStatus, expires_at: datetime | None, *, now: datetime) -> bool:
    """gateway 의 통과 판정과 같은 규칙입니다."""
    if status not in LIVE_STATUSES:
        return False
    return expires_at is None or expires_at > now


def is_transition_allowed(current: VKStatus, target: VKStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def rotation_expiry(
    current_expires_at: datetime | None, *, grace_until: datetime
) -> datetime:
    """로테이션 후 구 키의 만료 시각.

    유예가 원래 만료보다 늦으면 원래 만료를 유지합니다. **로테이션이 수명을 연장하면 안 됩니다.**
    """
    if current_expires_at is None:
        return grace_until
    return min(current_expires_at, grace_until)
