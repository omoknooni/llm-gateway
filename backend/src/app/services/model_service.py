"""모델 카탈로그.

alias 는 client 요청 값이자 gateway 의 캐시 키입니다. 그래서 **변경할 수 없고**,
삭제 대신 INACTIVE 로만 내립니다. 사용량 이력과 단가 이력이 alias 를 참조합니다.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, cache_keys
from app.core.auth import CurrentAdmin
from app.core.cache_invalidation import CacheInvalidationManager
from app.core.clock import utcnow
from app.core.deps import RequestContext
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.enums import ModelStatus, Provider
from app.models.model import ModelAlias, ModelPricing
from app.repositories.model_repository import ModelAliasRepository, ModelPricingRepository
from app.schemas.models import (
    ModelCreateRequest,
    ModelResponse,
    ModelStatusRequest,
    ModelUpdateRequest,
    PricingCreateRequest,
    PricingResponse,
)

logger = structlog.get_logger()


def _pricing_response(pricing: ModelPricing) -> PricingResponse:
    return PricingResponse(
        id=str(pricing.id),
        model_alias=pricing.model_alias,
        input_price_per_1k=pricing.input_price_per_1k,
        output_price_per_1k=pricing.output_price_per_1k,
        cache_write_price_per_1k=pricing.cache_write_price_per_1k,
        cache_read_price_per_1k=pricing.cache_read_price_per_1k,
        currency=pricing.currency,
        effective_from=pricing.effective_from,
        effective_until=pricing.effective_until,
        source=pricing.source,
    )


def _model_response(alias: ModelAlias, pricing: ModelPricing | None) -> ModelResponse:
    return ModelResponse(
        alias=alias.alias,
        display_name=alias.display_name,
        provider=alias.provider,
        provider_model_id=alias.provider_model_id,
        region=alias.region,
        endpoint_url=alias.endpoint_url,
        supported_dialects=list(alias.supported_dialects),
        status=alias.status,
        max_input_tokens=alias.max_input_tokens,
        max_output_tokens=alias.max_output_tokens,
        supports_streaming=alias.supports_streaming,
        description=alias.description,
        current_pricing=_pricing_response(pricing) if pricing else None,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
    )


class ModelService:
    def __init__(self, cache_mgr: CacheInvalidationManager) -> None:
        self._cache = cache_mgr

    async def create(
        self,
        session: AsyncSession,
        *,
        data: ModelCreateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> ModelResponse:
        alias_repo = ModelAliasRepository(session)
        if await alias_repo.get(data.alias) is not None:
            raise ConflictError("같은 alias 가 이미 있습니다", code="duplicate_alias")

        self._validate_endpoint(data.provider, data.endpoint_url)

        alias = ModelAlias(
            alias=data.alias,
            display_name=data.display_name,
            provider=data.provider,
            provider_model_id=data.provider_model_id,
            region=data.region,
            endpoint_url=data.endpoint_url,
            supported_dialects=data.supported_dialects,
            status=ModelStatus.ACTIVE,
            max_input_tokens=data.max_input_tokens,
            max_output_tokens=data.max_output_tokens,
            supports_streaming=data.supports_streaming,
            description=data.description,
            created_by=actor.user_id,
        )
        alias_repo.add(alias)

        pricing = self._build_pricing(data.alias, data.pricing, actor.user_id)
        ModelPricingRepository(session).add(pricing)

        await audit.record_for(
            session,
            actor,
            action="CREATE_MODEL_ALIAS",
            resource_type="model_alias",
            resource_id=alias.alias,
            changes={
                "after": {
                    "provider_model_id": alias.provider_model_id,
                    "supported_dialects": [d.value for d in data.supported_dialects],
                }
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await self._commit(session)
        await self._cache.invalidate(self._policy_keys(alias.alias))

        await session.refresh(alias)
        return _model_response(alias, pricing)

    async def get(self, session: AsyncSession, alias_name: str) -> ModelResponse:
        alias = await ModelAliasRepository(session).get(alias_name)
        if alias is None:
            raise NotFoundError("ModelAlias", alias_name)
        pricing = await ModelPricingRepository(session).current_for_alias(alias_name, at=utcnow())
        return _model_response(alias, pricing)

    async def list_models(
        self, session: AsyncSession, *, status: ModelStatus | None = None
    ) -> list[ModelResponse]:
        aliases = await ModelAliasRepository(session).list_aliases(status=status)
        pricing_repo = ModelPricingRepository(session)
        now = utcnow()
        return [
            _model_response(alias, await pricing_repo.current_for_alias(alias.alias, at=now))
            for alias in aliases
        ]

    async def update(
        self,
        session: AsyncSession,
        *,
        alias_name: str,
        data: ModelUpdateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> ModelResponse:
        repo = ModelAliasRepository(session)
        alias = await repo.get(alias_name, for_update=True)
        if alias is None:
            raise NotFoundError("ModelAlias", alias_name)

        before = {
            "provider_model_id": alias.provider_model_id,
            "region": alias.region,
            "supported_dialects": [d.value for d in alias.supported_dialects],
        }
        for field in (
            "display_name",
            "provider_model_id",
            "region",
            "endpoint_url",
            "max_input_tokens",
            "max_output_tokens",
            "supports_streaming",
            "description",
        ):
            value = getattr(data, field)
            if value is not None:
                setattr(alias, field, value)
        if data.supported_dialects is not None:
            alias.supported_dialects = data.supported_dialects
        self._validate_endpoint(alias.provider, alias.endpoint_url)

        await audit.record_for(
            session,
            actor,
            action="UPDATE_MODEL_ALIAS",
            resource_type="model_alias",
            resource_id=alias.alias,
            changes={
                "before": before,
                "after": {
                    "provider_model_id": alias.provider_model_id,
                    "region": alias.region,
                    "supported_dialects": [d.value for d in alias.supported_dialects],
                },
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await self._commit(session)
        await self._cache.invalidate(self._policy_keys(alias.alias))

        await session.refresh(alias)
        pricing = await ModelPricingRepository(session).current_for_alias(alias_name, at=utcnow())
        return _model_response(alias, pricing)

    async def set_status(
        self,
        session: AsyncSession,
        *,
        alias_name: str,
        data: ModelStatusRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> ModelResponse:
        """상태 전환.

        INACTIVE 전환은 '차단'이므로 캐시 삭제 실패를 조용히 넘기지 않습니다.
        """
        repo = ModelAliasRepository(session)
        alias = await repo.get(alias_name, for_update=True)
        if alias is None:
            raise NotFoundError("ModelAlias", alias_name)

        if data.status == ModelStatus.ACTIVE:
            pricing = await ModelPricingRepository(session).current_for_alias(alias_name, at=utcnow())
            if pricing is None:
                raise ValidationError(
                    "현재 유효한 단가가 없는 모델은 활성화할 수 없습니다", code="pricing_required"
                )

        before = alias.status
        alias.status = data.status
        await audit.record_for(
            session,
            actor,
            action="SET_MODEL_STATUS",
            resource_type="model_alias",
            resource_id=alias.alias,
            changes={"before": {"status": before.value}, "after": {"status": data.status.value}},
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await self._commit(session)

        result = await self._cache.invalidate(self._policy_keys(alias.alias))
        if data.status == ModelStatus.INACTIVE and not result.ok:
            logger.warning("model_service.inactive_cache_not_cleared", alias=alias.alias)

        await session.refresh(alias)
        pricing = await ModelPricingRepository(session).current_for_alias(alias_name, at=utcnow())
        return _model_response(alias, pricing)

    async def add_pricing(
        self,
        session: AsyncSession,
        *,
        alias_name: str,
        data: PricingCreateRequest,
        actor: CurrentAdmin,
        ctx: RequestContext,
    ) -> PricingResponse:
        """새 단가를 등록하고 이전 구간을 닫습니다. 기존 행은 수정하지 않습니다."""
        alias_repo = ModelAliasRepository(session)
        if await alias_repo.get(alias_name) is None:
            raise NotFoundError("ModelAlias", alias_name)

        pricing_repo = ModelPricingRepository(session)
        open_ended = await pricing_repo.open_ended_for_alias(alias_name)
        if open_ended is not None:
            if data.effective_from <= open_ended.effective_from:
                raise ConflictError(
                    "새 단가의 시작 시점이 기존 구간보다 앞설 수 없습니다",
                    code="pricing_period_overlap",
                    details={"open_from": open_ended.effective_from.isoformat()},
                )
            open_ended.effective_until = data.effective_from

        pricing = self._build_pricing(alias_name, data, actor.user_id)
        pricing_repo.add(pricing)

        await audit.record_for(
            session,
            actor,
            action="SET_MODEL_PRICING",
            resource_type="model_alias",
            resource_id=alias_name,
            changes={
                "after": {
                    "input_price_per_1k": str(data.input_price_per_1k),
                    "output_price_per_1k": str(data.output_price_per_1k),
                    "effective_from": data.effective_from.isoformat(),
                }
            },
            ip_address=ctx.ip_address,
            request_id=ctx.request_id,
        )
        await self._commit(session)
        await self._cache.invalidate(self._policy_keys(alias_name))

        return _pricing_response(pricing)

    async def list_pricings(self, session: AsyncSession, alias_name: str) -> list[PricingResponse]:
        if await ModelAliasRepository(session).get(alias_name) is None:
            raise NotFoundError("ModelAlias", alias_name)
        rows = await ModelPricingRepository(session).list_for_alias(alias_name)
        return [_pricing_response(row) for row in rows]

    async def aliases_missing_pricing(self, session: AsyncSession) -> list[str]:
        """ACTIVE 인데 현재 유효 단가가 없는 alias. 운영 화면 배지와 주기 점검이 씁니다."""
        return await ModelPricingRepository(session).aliases_without_current_pricing(at=utcnow())

    # ── 내부 ──

    @staticmethod
    def _policy_keys(alias_name: str) -> list[str]:
        """카탈로그 변경 시 지울 캐시 키.

        목록 키를 항상 함께 지웁니다(09 문서 Q1). 목록 항목이 `supported_dialects` 와
        `max_output_tokens` 를 싣고 있어서, 상태 전환만 트리거로 잡으면 방언이 바뀐 모델이
        `/v1/models` 에 옛 값으로 남습니다.
        """
        return [cache_keys.model_policy(alias_name), cache_keys.model_list()]

    @staticmethod
    def _validate_endpoint(provider: Provider, endpoint_url: str | None) -> None:
        """Mantle 은 엔드포인트가 있어야 부를 수 있습니다.

        DB CHECK 와 이중 방어입니다. 제약은 새로 들어오는 행만 막고, 여기서는 사람이 읽는
        오류 메시지를 줍니다.
        """
        if provider == Provider.BEDROCK_MANTLE and not endpoint_url:
            raise ValidationError(
                "BEDROCK_MANTLE 모델은 endpoint_url 이 필요합니다", code="endpoint_url_required"
            )

    @staticmethod
    def _build_pricing(alias: str, data: PricingCreateRequest, actor_id: uuid.UUID) -> ModelPricing:
        return ModelPricing(
            id=uuid.uuid4(),
            model_alias=alias,
            input_price_per_1k=data.input_price_per_1k,
            output_price_per_1k=data.output_price_per_1k,
            cache_write_price_per_1k=data.cache_write_price_per_1k,
            cache_read_price_per_1k=data.cache_read_price_per_1k,
            effective_from=data.effective_from,
            source=data.source,
            created_by=actor_id,
        )

    @staticmethod
    async def _commit(session: AsyncSession) -> None:
        """구간 겹침은 DB 의 EXCLUDE 제약이 최종 판정합니다.

        애플리케이션 검증만으로는 동시 요청에서 겹칩니다. 제약 위반을 409 로 옮깁니다.
        """
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if "ex_model_pricings_no_overlap" in str(exc.orig):
                raise ConflictError(
                    "단가 유효 구간이 겹칩니다", code="pricing_period_overlap"
                ) from exc
            raise
