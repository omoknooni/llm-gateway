"""Virtual Key 관리."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response, status

from app.core.auth import AdminDep, RequireAdmin, RequireAdminOrLeader, ensure_team_scope
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.core.exceptions import ForbiddenError
from app.models.enums import VKOwnerType, VKStatus
from app.policy.virtual_key import RevokeReason
from app.schemas.common import Page
from app.schemas.virtual_keys import (
    TeamRevokeAllRequest,
    TeamRevokeAllResponse,
    VirtualKeyAuditResponse,
    VirtualKeyCreateRequest,
    VirtualKeyCreateResponse,
    VirtualKeyResponse,
    VirtualKeyRotateRequest,
    VirtualKeyUpdateRequest,
)
from app.services.virtual_key_service import VirtualKeyService

router = APIRouter(prefix="/virtual-keys", tags=["Virtual Key"])


@router.post("", response_model=VirtualKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def issue_virtual_key(
    payload: VirtualKeyCreateRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> VirtualKeyCreateResponse:
    """VK 를 발급합니다. **원문은 이 응답에서만** 볼 수 있습니다."""
    if not actor.is_admin and payload.owner_type == VKOwnerType.TEAM:
        ensure_team_scope(actor, uuid.UUID(payload.owner_id))
    return await VirtualKeyService(cache).issue(session, data=payload, actor=actor, ctx=ctx)


@router.get("", response_model=Page[VirtualKeyResponse])
async def list_virtual_keys(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    owner_type: VKOwnerType | None = Query(default=None),
    owner_id: uuid.UUID | None = Query(default=None),
    team_id: uuid.UUID | None = Query(default=None),
    key_status: VKStatus | None = Query(default=None, alias="status"),
    expires_before: datetime | None = Query(default=None, description="만료 임박 키 조회"),
    unused_since: datetime | None = Query(default=None, description="장기 미사용 키 조회"),
    q: str | None = Query(default=None, description="이름 또는 prefix 부분 일치"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[VirtualKeyResponse]:
    if not actor.is_admin:
        if team_id is not None:
            ensure_team_scope(actor, team_id)
        team_id = actor.team_id
        if team_id is None:
            raise ForbiddenError("팀에 소속되지 않은 사용자는 목록을 조회할 수 없습니다")

    return await VirtualKeyService(cache).list_keys(
        session,
        owner_type=owner_type,
        owner_id=owner_id,
        team_id=team_id,
        status=key_status,
        expires_before=expires_before,
        unused_since=unused_since,
        query=q,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{key_id}", response_model=VirtualKeyResponse)
async def get_virtual_key(
    key_id: uuid.UUID, actor: AdminDep, session: SessionDep, cache: CacheDep
) -> VirtualKeyResponse:
    key = await VirtualKeyService(cache).get(session, key_id)
    _ensure_key_access(actor, key)
    return key


@router.patch("/{key_id}", response_model=VirtualKeyResponse)
async def update_virtual_key(
    key_id: uuid.UUID,
    payload: VirtualKeyUpdateRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> VirtualKeyResponse:
    """이름, 허용 모델, 만료 시각(단축만)을 수정합니다."""
    service = VirtualKeyService(cache)
    _ensure_key_access(actor, await service.get(session, key_id))
    return await service.update(session, key_id=key_id, data=payload, actor=actor, ctx=ctx)


@router.post("/{key_id}/rotate", response_model=VirtualKeyCreateResponse)
async def rotate_virtual_key(
    key_id: uuid.UUID,
    payload: VirtualKeyRotateRequest,
    actor: RequireAdminOrLeader,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> VirtualKeyCreateResponse:
    """유예 기간을 둔 교체. 구 키는 유예 동안 계속 인증됩니다."""
    service = VirtualKeyService(cache)
    _ensure_key_access(actor, await service.get(session, key_id))
    return await service.rotate(session, key_id=key_id, data=payload, actor=actor, ctx=ctx)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_virtual_key(
    key_id: uuid.UUID,
    actor: AdminDep,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    response: Response,
    reason: RevokeReason = Query(description="폐기 사유. 감사 요구사항이라 필수입니다"),
    note: str | None = Query(default=None, max_length=255),
) -> None:
    """폐기합니다. 이미 폐기된 키에 대해서도 204 로 멱등하게 응답합니다."""
    service = VirtualKeyService(cache)
    key = await service.get(session, key_id)
    _ensure_key_access(actor, key, allow_owner=True)

    invalidated = await service.revoke(
        session, key_id=key_id, reason=reason, note=note, actor=actor, ctx=ctx
    )
    # 캐시 삭제 실패는 응답 헤더로 드러냅니다. 폐기는 즉시 반영되어야 하는 조작입니다.
    response.headers["x-cache-invalidated"] = "true" if invalidated else "false"


@router.get("/{key_id}/audit", response_model=VirtualKeyAuditResponse)
async def get_virtual_key_audit(
    key_id: uuid.UUID, actor: RequireAdminOrLeader, session: SessionDep, cache: CacheDep
) -> VirtualKeyAuditResponse:
    """이 키와 로테이션 체인 전체의 감사 이력."""
    service = VirtualKeyService(cache)
    _ensure_key_access(actor, await service.get(session, key_id))
    return await service.get_audit(session, key_id)


team_router = APIRouter(prefix="/teams", tags=["Virtual Key"])


@team_router.post("/{team_id}/virtual-keys/revoke-all", response_model=TeamRevokeAllResponse)
async def revoke_team_virtual_keys(
    team_id: uuid.UUID,
    payload: TeamRevokeAllRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
) -> TeamRevokeAllResponse:
    """사고 대응용 일괄 폐기. **되돌릴 수 없고 client 가 즉시 깨집니다.**"""
    return await VirtualKeyService(cache).revoke_team_keys(
        session,
        team_id=team_id,
        confirm_team_name=payload.confirm_team_name,
        reason=payload.reason,
        actor=actor,
        ctx=ctx,
    )


def _ensure_key_access(actor, key: VirtualKeyResponse, *, allow_owner: bool = False) -> None:
    if actor.is_admin:
        return
    if allow_owner and key.owner_type == VKOwnerType.USER and str(actor.user_id) == key.owner_id:
        return
    ensure_team_scope(actor, uuid.UUID(key.team_id))
