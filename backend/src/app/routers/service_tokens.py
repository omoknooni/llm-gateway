"""서비스 토큰 관리. 외부 시스템·배치가 Admin API 를 호출할 때 쓰는 자격 증명입니다."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.core.auth import RequireAdmin
from app.core.db import SessionDep
from app.core.deps import CtxDep
from app.schemas.service_tokens import (
    ServiceTokenCreateRequest,
    ServiceTokenCreateResponse,
    ServiceTokenResponse,
)
from app.services.service_token_service import ServiceTokenService

router = APIRouter(prefix="/service-tokens", tags=["Service Token"])


@router.post("", response_model=ServiceTokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def issue_service_token(
    payload: ServiceTokenCreateRequest, actor: RequireAdmin, session: SessionDep, ctx: CtxDep
) -> ServiceTokenCreateResponse:
    """토큰을 발급합니다. **원문은 이 응답에서만** 볼 수 있습니다."""
    return await ServiceTokenService().issue(
        session,
        name=payload.name,
        expires_in_days=payload.expires_in_days,
        actor=actor,
        ip_address=ctx.ip_address,
        request_id=ctx.request_id,
    )


@router.get("", response_model=list[ServiceTokenResponse])
async def list_service_tokens(
    actor: RequireAdmin,
    session: SessionDep,
    include_revoked: bool = Query(default=False),
) -> list[ServiceTokenResponse]:
    return await ServiceTokenService().list_tokens(session, include_revoked=include_revoked)


@router.post("/{token_id}/rotate", response_model=ServiceTokenCreateResponse)
async def rotate_service_token(
    token_id: uuid.UUID,
    payload: ServiceTokenCreateRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
) -> ServiceTokenCreateResponse:
    """새 토큰을 발급하고 구 토큰을 즉시 폐기합니다."""
    return await ServiceTokenService().rotate(
        session,
        token_id=token_id,
        expires_in_days=payload.expires_in_days,
        actor=actor,
        ip_address=ctx.ip_address,
        request_id=ctx.request_id,
    )


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_service_token(
    token_id: uuid.UUID, actor: RequireAdmin, session: SessionDep, ctx: CtxDep
) -> None:
    await ServiceTokenService().revoke(
        session,
        token_id=token_id,
        actor=actor,
        ip_address=ctx.ip_address,
        request_id=ctx.request_id,
    )
