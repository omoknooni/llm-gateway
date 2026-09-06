"""서비스 토큰 발급·로테이션·폐기.

외부 시스템·배치가 Admin API 를 호출할 때 쓰는 자격 증명입니다. VK 와 마찬가지로
**원문을 저장하지 않고** sha256 해시만 둡니다.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.auth import SERVICE_TOKEN_PREFIX, CurrentAdmin, hash_token
from app.core.clock import utcnow
from app.core.exceptions import NotFoundError
from app.models.auth import ServiceToken
from app.repositories.service_token_repository import ServiceTokenRepository
from app.schemas.service_tokens import ServiceTokenCreateResponse, ServiceTokenResponse

_TOKEN_BYTES = 32


def _generate_token() -> tuple[str, str, str]:
    """(원문, 해시, 표시용 prefix)."""
    raw = SERVICE_TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    return raw, hash_token(raw), raw[: len(SERVICE_TOKEN_PREFIX) + 8]


def _to_response(token: ServiceToken) -> ServiceTokenResponse:
    return ServiceTokenResponse(
        id=str(token.id),
        name=token.name,
        token_prefix=token.token_prefix,
        expires_at=token.expires_at,
        revoked_at=token.revoked_at,
        rotated_from_id=str(token.rotated_from_id) if token.rotated_from_id else None,
        created_at=token.created_at,
    )


class ServiceTokenService:
    async def issue(
        self,
        session: AsyncSession,
        *,
        name: str,
        expires_in_days: int,
        actor: CurrentAdmin,
        ip_address: str | None = None,
        request_id: str = "",
    ) -> ServiceTokenCreateResponse:
        raw, token_hash, prefix = _generate_token()
        token = ServiceToken(
            id=uuid.uuid4(),
            name=name,
            token_hash=token_hash,
            token_prefix=prefix,
            expires_at=utcnow() + timedelta(days=expires_in_days),
            created_by=actor.user_id,
        )
        ServiceTokenRepository(session).add(token)

        await audit.record_for(
            session,
            actor,
            action="CREATE_SERVICE_TOKEN",
            resource_type="service_token",
            resource_id=str(token.id),
            changes={"after": {"name": name, "token_prefix": prefix}},
            ip_address=ip_address,
            request_id=request_id,
        )
        await session.commit()
        await session.refresh(token)

        return ServiceTokenCreateResponse(**_to_response(token).model_dump(), token=raw)

    async def list_tokens(
        self, session: AsyncSession, *, include_revoked: bool = False
    ) -> list[ServiceTokenResponse]:
        tokens = await ServiceTokenRepository(session).list_all(include_revoked=include_revoked)
        return [_to_response(token) for token in tokens]

    async def rotate(
        self,
        session: AsyncSession,
        *,
        token_id: uuid.UUID,
        expires_in_days: int,
        actor: CurrentAdmin,
        ip_address: str | None = None,
        request_id: str = "",
    ) -> ServiceTokenCreateResponse:
        repo = ServiceTokenRepository(session)
        old = await repo.get(token_id)
        if old is None:
            raise NotFoundError("ServiceToken", str(token_id))

        raw, token_hash, prefix = _generate_token()
        new = ServiceToken(
            id=uuid.uuid4(),
            name=old.name,
            token_hash=token_hash,
            token_prefix=prefix,
            expires_at=utcnow() + timedelta(days=expires_in_days),
            rotated_from_id=old.id,
            created_by=actor.user_id,
        )
        repo.add(new)
        # 구 토큰은 즉시 폐기합니다. 서비스 토큰은 VK 와 달리 점진 전환 요구가 없습니다.
        old.revoked_at = utcnow()

        await audit.record_for(
            session,
            actor,
            action="ROTATE_SERVICE_TOKEN",
            resource_type="service_token",
            resource_id=str(new.id),
            changes={"before": {"id": str(old.id), "token_prefix": old.token_prefix},
                     "after": {"id": str(new.id), "token_prefix": prefix}},
            ip_address=ip_address,
            request_id=request_id,
        )
        await session.commit()
        await session.refresh(new)

        return ServiceTokenCreateResponse(**_to_response(new).model_dump(), token=raw)

    async def revoke(
        self,
        session: AsyncSession,
        *,
        token_id: uuid.UUID,
        actor: CurrentAdmin,
        ip_address: str | None = None,
        request_id: str = "",
    ) -> None:
        repo = ServiceTokenRepository(session)
        token = await repo.get(token_id)
        if token is None:
            raise NotFoundError("ServiceToken", str(token_id))
        if token.revoked_at is not None:
            return  # 멱등. 재시도 안전.

        token.revoked_at = utcnow()
        await audit.record_for(
            session,
            actor,
            action="REVOKE_SERVICE_TOKEN",
            resource_type="service_token",
            resource_id=str(token.id),
            changes={"before": {"revoked": False}, "after": {"revoked": True}},
            ip_address=ip_address,
            request_id=request_id,
        )
        await session.commit()
