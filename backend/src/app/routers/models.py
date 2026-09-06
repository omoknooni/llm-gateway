"""모델 카탈로그와 단가."""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, status

from app.core.auth import AdminDep, RequireAdmin
from app.core.db import SessionDep
from app.core.deps import CacheDep, CtxDep
from app.models.enums import ModelStatus
from app.schemas.models import (
    ModelCreateRequest,
    ModelResponse,
    ModelStatusRequest,
    ModelUpdateRequest,
    PricingCreateRequest,
    PricingResponse,
)
from app.services.model_service import ModelService

router = APIRouter(prefix="/models", tags=["Model Catalog"])

AliasPath = Path(description="모델 alias", pattern=r"^[a-z0-9][a-z0-9.-]{1,127}$")


@router.post("", response_model=ModelResponse, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreateRequest, actor: RequireAdmin, session: SessionDep, ctx: CtxDep, cache: CacheDep
) -> ModelResponse:
    """alias 를 등록합니다. 초기 단가를 함께 받습니다.

    단가 없이 활성 상태가 되면 비용이 0 으로 집계되어 관제 목적이 무너집니다.
    """
    return await ModelService(cache).create(session, data=payload, actor=actor, ctx=ctx)


@router.get("", response_model=list[ModelResponse])
async def list_models(
    actor: AdminDep,
    session: SessionDep,
    cache: CacheDep,
    model_status: ModelStatus | None = Query(default=None, alias="status"),
) -> list[ModelResponse]:
    return await ModelService(cache).list_models(session, status=model_status)


@router.get("/missing-pricing", response_model=list[str])
async def list_models_missing_pricing(
    actor: RequireAdmin, session: SessionDep, cache: CacheDep
) -> list[str]:
    """ACTIVE 인데 현재 유효 단가가 없는 alias. 운영 화면 배지가 씁니다."""
    return await ModelService(cache).aliases_missing_pricing(session)


@router.get("/{alias}", response_model=ModelResponse)
async def get_model(
    actor: AdminDep, session: SessionDep, cache: CacheDep, alias: str = AliasPath
) -> ModelResponse:
    return await ModelService(cache).get(session, alias)


@router.patch("/{alias}", response_model=ModelResponse)
async def update_model(
    payload: ModelUpdateRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    alias: str = AliasPath,
) -> ModelResponse:
    """alias 자체는 바꿀 수 없습니다. 이름을 바꾸려면 새 alias 를 만들고 구 alias 를 내립니다."""
    return await ModelService(cache).update(
        session, alias_name=alias, data=payload, actor=actor, ctx=ctx
    )


@router.patch("/{alias}/status", response_model=ModelResponse)
async def set_model_status(
    payload: ModelStatusRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    alias: str = AliasPath,
) -> ModelResponse:
    return await ModelService(cache).set_status(
        session, alias_name=alias, data=payload, actor=actor, ctx=ctx
    )


@router.post("/{alias}/pricings", response_model=PricingResponse, status_code=status.HTTP_201_CREATED)
async def add_pricing(
    payload: PricingCreateRequest,
    actor: RequireAdmin,
    session: SessionDep,
    ctx: CtxDep,
    cache: CacheDep,
    alias: str = AliasPath,
) -> PricingResponse:
    """새 단가를 등록하고 이전 구간을 닫습니다. 기존 단가 행은 수정하지 않습니다."""
    return await ModelService(cache).add_pricing(
        session, alias_name=alias, data=payload, actor=actor, ctx=ctx
    )


@router.get("/{alias}/pricings", response_model=list[PricingResponse])
async def list_pricings(
    actor: RequireAdmin, session: SessionDep, cache: CacheDep, alias: str = AliasPath
) -> list[PricingResponse]:
    return await ModelService(cache).list_pricings(session, alias)
