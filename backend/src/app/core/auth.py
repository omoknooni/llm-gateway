"""관리자 인증과 인가.

검증 경로는 네 갈래입니다(00 문서). 순서는 아래 코드가 계약입니다.

  1. dev 토큰      — DEV_LOGIN_ENABLED=true 인 로컬 개발에서만
  2. 서비스 토큰   — `svc-` 접두사. auth.service_tokens 의 sha256 해시로 대조
  3. OIDC 토큰     — JWKS 서명 검증
  4. Admin JWT     — auth.admin_jwt_configs 의 공개키로 검증

관리자 토큰과 Virtual Key 는 **완전히 다른 자격 증명**입니다. 이 모듈은 VK 를 모릅니다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.db import SessionDep
from app.core.exceptions import ForbiddenError, UnauthenticatedError
from app.models.auth import AdminJWTConfig, ServiceToken, User
from app.models.enums import UserRole

logger = structlog.get_logger()

SESSION_COOKIE_NAME = "admin_session"
SERVICE_TOKEN_PREFIX = "svc-"
DEV_TOKEN_PREFIX = "dev."

#: 합성 주체용 예약 UUID. 사람 계정과 섞이지 않게 고정값을 씁니다.
DEV_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
SERVICE_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")

#: last_login_at 갱신 최소 간격(초). 매 요청 UPDATE 를 피합니다.
_LOGIN_TOUCH_INTERVAL = 600


@dataclass
class CurrentAdmin:
    """인증된 주체. provider 와 무관한 동일 구조체입니다."""

    user_id: uuid.UUID
    email: str
    role: UserRole
    team_id: uuid.UUID | None = None
    is_service_token: bool = False
    service_token_id: uuid.UUID | None = None
    groups: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


def hash_token(raw: str) -> str:
    """서비스 토큰과 VK 가 공유하는 해시 규약(08 문서 C1)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AdminJWTVerifier:
    """`auth.admin_jwt_configs` 의 공개키로 RS256 토큰을 검증합니다.

    설정은 기동 시 로드합니다. 비밀키는 다루지 않습니다.
    """

    def __init__(self) -> None:
        self._configs: dict[str, dict[str, Any]] = {}

    def load(self, configs: list[AdminJWTConfig]) -> None:
        self._configs = {
            str(cfg.id): {
                "pem": cfg.public_key_pem,
                "issuer": cfg.issuer,
                "audience": cfg.audience,
                "algorithm": cfg.algorithm,
            }
            for cfg in configs
        }
        logger.info("admin_jwt.loaded", key_count=len(self._configs))

    @property
    def enabled(self) -> bool:
        return bool(self._configs)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except JWTError as exc:
            raise UnauthenticatedError("토큰 형식이 올바르지 않습니다") from exc

        # kid 가 맞으면 그 키만, 아니면 활성 키 전부를 시도합니다.
        candidates = [self._configs[kid]] if kid in self._configs else list(self._configs.values())
        if not candidates:
            raise UnauthenticatedError("토큰 서명 키를 찾을 수 없습니다")

        for cfg in candidates:
            try:
                return jwt.decode(
                    token,
                    cfg["pem"],
                    algorithms=[cfg["algorithm"]],
                    issuer=cfg["issuer"],
                    audience=cfg["audience"],
                )
            except JWTError:
                continue
        raise UnauthenticatedError("토큰 검증에 실패했습니다")


async def load_admin_jwt_configs(session: AsyncSession) -> list[AdminJWTConfig]:
    rows = await session.execute(select(AdminJWTConfig).where(AdminJWTConfig.is_active.is_(True)))
    return list(rows.scalars().all())


def extract_token(request: Request) -> str:
    """Authorization 헤더 또는 세션 쿠키에서 토큰을 꺼냅니다."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()

    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie:
        return cookie.strip()

    raise UnauthenticatedError("인증 토큰이 없습니다")


def _parse_dev_token(token: str) -> dict[str, Any] | None:
    """`dev.<base64url(json)>.<sig>` 형식. 서명은 검증하지 않습니다.

    로컬 개발 전용이고, 운영에서는 `Settings.validate_runtime` 이 기동을 막습니다.
    """
    if not token.startswith(DEV_TOKEN_PREFIX):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, binascii.Error):
        return None


def _claim_groups(claims: dict[str, Any], claim_name: str) -> list[str]:
    raw = claims.get(claim_name) or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item) for item in raw]


def _bootstrap_role(settings: Settings, email: str, groups: list[str]) -> UserRole | None:
    """설정으로 ADMIN 을 부여합니다. 첫 관리자를 만들 방법이 필요합니다."""
    if email and email.lower() in {item.lower() for item in settings.ADMIN_EMAILS}:
        return UserRole.ADMIN
    if set(groups) & set(settings.ADMIN_GROUPS):
        return UserRole.ADMIN
    return None


async def _resolve_service_token(session: AsyncSession, token: str) -> CurrentAdmin:
    now = utcnow()
    row = await session.execute(
        select(ServiceToken).where(
            ServiceToken.token_hash == hash_token(token),
            ServiceToken.revoked_at.is_(None),
            ServiceToken.expires_at > now,
        )
    )
    service_token = row.scalar_one_or_none()
    if service_token is None:
        raise UnauthenticatedError("유효하지 않거나 만료된 서비스 토큰입니다")

    return CurrentAdmin(
        user_id=SERVICE_ACTOR_ID,
        email=f"service-token:{service_token.name}",
        role=UserRole.ADMIN,
        is_service_token=True,
        service_token_id=service_token.id,
    )


async def _resolve_user_from_claims(
    session: AsyncSession, settings: Settings, claims: dict[str, Any], *, provider: str
) -> CurrentAdmin:
    subject = str(claims.get(settings.OIDC_USER_ID_CLAIM) or "")
    email = str(claims.get(settings.OIDC_EMAIL_CLAIM) or "")
    groups = _claim_groups(claims, settings.OIDC_GROUPS_CLAIM)

    user: User | None = None
    if subject:
        user = (
            await session.execute(select(User).where(User.idp_subject == subject))
        ).scalar_one_or_none()
    if user is None and email:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None:
        # JIT 프로비저닝은 그룹 → 팀 매핑이 확정된 뒤에 켭니다(02 문서 / 07 미결정 #1).
        logger.info("auth.unknown_subject", subject=subject, email=email)
        raise UnauthenticatedError("등록되지 않은 사용자입니다")
    if not user.is_active:
        raise UnauthenticatedError("비활성화된 사용자입니다")

    role = _bootstrap_role(settings, user.email, groups) or user.role

    # idp_subject 연결은 최초 1회, last_login_at 은 간격을 둬 갱신합니다(매 요청 UPDATE 방지).
    touched = False
    if subject and user.idp_subject is None:
        user.idp_subject = subject
        user.provider = provider
        touched = True
    if user.last_login_at is None or (utcnow() - user.last_login_at).total_seconds() > _LOGIN_TOUCH_INTERVAL:
        user.last_login_at = utcnow()
        touched = True
    if touched:
        await session.commit()

    return CurrentAdmin(
        user_id=user.id,
        email=user.email,
        role=role,
        team_id=user.team_id,
        groups=groups,
    )


async def get_current_admin(request: Request, session: SessionDep) -> CurrentAdmin:
    settings = get_settings()
    token = extract_token(request)

    if settings.DEV_LOGIN_ENABLED:
        payload = _parse_dev_token(token)
        if payload is not None:
            return CurrentAdmin(
                user_id=uuid.UUID(payload["user_id"]) if payload.get("user_id") else DEV_ACTOR_ID,
                email=payload.get("email", "admin@dev.local"),
                role=UserRole(payload.get("role", UserRole.ADMIN.value)),
                team_id=uuid.UUID(payload["team_id"]) if payload.get("team_id") else None,
            )

    if token.startswith(SERVICE_TOKEN_PREFIX):
        return await _resolve_service_token(session, token)

    oidc_verifier = getattr(request.app.state, "oidc_verifier", None)
    if oidc_verifier is not None:
        claims = await oidc_verifier.verify(token)
        return await _resolve_user_from_claims(
            session, settings, claims, provider=settings.OIDC_PROVIDER_NAME
        )

    admin_jwt: AdminJWTVerifier | None = getattr(request.app.state, "admin_jwt_verifier", None)
    if admin_jwt is not None and admin_jwt.enabled:
        claims = admin_jwt.verify(token)
        return await _resolve_user_from_claims(session, settings, claims, provider="admin-jwt")

    raise UnauthenticatedError("사용 가능한 인증 경로가 없습니다")


AdminDep = Annotated[CurrentAdmin, Depends(get_current_admin)]


async def require_admin(actor: AdminDep) -> CurrentAdmin:
    if actor.role != UserRole.ADMIN:
        raise ForbiddenError("ADMIN 권한이 필요합니다")
    return actor


async def require_admin_or_leader(actor: AdminDep) -> CurrentAdmin:
    if actor.role not in (UserRole.ADMIN, UserRole.TEAM_LEADER):
        raise ForbiddenError("ADMIN 또는 TEAM_LEADER 권한이 필요합니다")
    return actor


RequireAdmin = Annotated[CurrentAdmin, Depends(require_admin)]
RequireAdminOrLeader = Annotated[CurrentAdmin, Depends(require_admin_or_leader)]


def ensure_team_scope(actor: CurrentAdmin, team_id: uuid.UUID | None) -> None:
    """팀 범위 리소스 접근 검사.

    다른 팀 리소스를 지정하면 404 가 아니라 403 입니다(00 문서). 존재 여부를 숨기는 것보다
    권한 경계를 분명히 알려주는 편이 운영에 낫습니다.
    """
    if actor.role == UserRole.ADMIN:
        return
    if team_id is not None and actor.team_id == team_id:
        return
    raise ForbiddenError("해당 팀에 대한 권한이 없습니다")


def ensure_self_or_privileged(actor: CurrentAdmin, user_id: uuid.UUID) -> None:
    if actor.role == UserRole.ADMIN or actor.user_id == user_id:
        return
    raise ForbiddenError("본인 또는 ADMIN 만 접근할 수 있습니다")
