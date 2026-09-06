"""모델 alias 해석.

client 가 보낸 문자열을 `ModelConfig` 로 바꿉니다. alias 와 provider_model_id 를 **둘 다**
수용합니다 — client 가 `apac.anthropic.claude-...` 를 그대로 보내는 경우가 실제로 있습니다.

`status = INACTIVE` 는 운영자의 kill switch 입니다. 다른 모델로 조용히 우회시키지 않고
거절합니다. 우회시키면 끈 모델의 트래픽이 다른 모델의 비용으로 나타나 원인 추적이
불가능해집니다(docs/04).
"""

from __future__ import annotations

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from gateway.config import Settings
from gateway.core import cache, cache_keys
from gateway.core.errors import ErrorCode, GatewayError
from gateway.core.model import ModelConfig, ModelPricing
from gateway.schema.base import ModelStatus
from gateway.schema.model import ModelAlias
from gateway.schema.model import ModelPricing as ModelPricingRow

logger = structlog.get_logger(__name__)


def _not_found(model_ref: str) -> GatewayError:
    """미등록과 INACTIVE 를 client 에게 같은 답으로 돌려줍니다.

    구분해 주면 카탈로그에 무엇이 있는지 열거할 수 있게 됩니다. 우리 쪽 구분은 로그와
    `auth_events` 에 남습니다.
    """
    from gateway.core.errors import AuthOutcome

    return GatewayError(
        ErrorCode.MODEL_INACTIVE,
        f"Model '{model_ref}' is not available",
        outcome=AuthOutcome.MODEL_INACTIVE,
    )


async def load_active_aliases(db: AsyncSession, redis, ttl: int) -> tuple[str, ...]:
    """카탈로그의 ACTIVE alias 목록.

    `/v1/models` 응답의 재료이면서 허용 모델 3층 해석에서 "team 층 0개 → 카탈로그 전체"의
    재료이기도 합니다. 그래서 backend 는 `model_aliases` 의 모든 변경에서 이 키를 지웁니다
    (docs/06 Q1).
    """
    cached = await cache.get_json(redis, cache_keys.model_list())
    if cached is not None:
        return tuple(cached)

    aliases = tuple(
        (
            await db.execute(select(ModelAlias.alias).where(ModelAlias.status == ModelStatus.ACTIVE))
        ).scalars().all()
    )
    await cache.set_json(redis, cache_keys.model_list(), list(aliases), ttl)
    return aliases


class ModelResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def resolve(
        self, *, model_ref: str, redis, session_factory: async_sessionmaker[AsyncSession] | None
    ) -> ModelConfig:
        cached = await cache.get_json(redis, cache_keys.model_policy(model_ref))
        if cached is not None:
            try:
                config = ModelConfig.from_dict(cached)
            except Exception:
                logger.warning("model.cache_shape_invalid", model_ref=model_ref)
                config = None
            if config is not None:
                return self._ensure_active(config, model_ref)

        if session_factory is None:
            raise GatewayError(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "Service temporarily unavailable"
            )

        try:
            async with session_factory() as db:
                config = await self._load(db, redis, model_ref)
        except GatewayError:
            raise
        except SQLAlchemyError as exc:
            logger.warning("model.database_unavailable", error=str(exc))
            raise GatewayError(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "Service temporarily unavailable"
            ) from exc

        return config

    async def active_aliases(
        self, *, redis, session_factory: async_sessionmaker[AsyncSession] | None
    ) -> tuple[str, ...]:
        cached = await cache.get_json(redis, cache_keys.model_list())
        if cached is not None:
            return tuple(cached)
        if session_factory is None:
            return ()
        async with session_factory() as db:
            return await load_active_aliases(db, redis, self._settings.policy_cache_ttl_seconds)

    def _ensure_active(self, config: ModelConfig, model_ref: str) -> ModelConfig:
        if config.status != ModelStatus.ACTIVE:
            logger.info("model.inactive", alias=config.alias, model_ref=model_ref)
            raise _not_found(model_ref)
        if config.provider == "BEDROCK_MANTLE" and not config.endpoint_url:
            # DB CHECK 제약이 새로 들어오는 행을 막지만, 제약 도입 이전 행이나 직접 SQL 로
            # 넣은 행은 막지 못합니다. 첫 호출에서 알 수 없는 실패를 내는 대신 여기서 끊습니다.
            logger.warning("model.mantle_endpoint_missing", alias=config.alias)
            raise _not_found(model_ref)
        return config

    async def _load(self, db: AsyncSession, redis, model_ref: str) -> ModelConfig:
        row = (
            await db.execute(
                select(ModelAlias)
                .where(or_(ModelAlias.alias == model_ref, ModelAlias.provider_model_id == model_ref))
                # alias 정확 매칭을 먼저 봅니다. 같은 provider_model_id 가 여러 alias 에
                # 매핑될 수 있어 순서를 고정하지 않으면 요청마다 다른 행이 잡힙니다.
                .order_by((ModelAlias.alias == model_ref).desc(), ModelAlias.alias)
                .limit(1)
            )
        ).scalar_one_or_none()

        if row is None:
            logger.info("model.unknown", model_ref=model_ref)
            raise _not_found(model_ref)

        pricing_row = await self._latest_pricing(db, row.alias)
        config = ModelConfig(
            alias=row.alias,
            provider=str(row.provider),
            provider_model_id=row.provider_model_id,
            region=row.region,
            endpoint_url=row.endpoint_url,
            supported_dialects=tuple(str(d) for d in row.supported_dialects),
            status=str(row.status),
            max_input_tokens=row.max_input_tokens,
            max_output_tokens=row.max_output_tokens,
            supports_streaming=row.supports_streaming,
            pricing=(
                ModelPricing(
                    input_per_1k=pricing_row.input_price_per_1k,
                    output_per_1k=pricing_row.output_price_per_1k,
                    cache_write_per_1k=pricing_row.cache_write_price_per_1k,
                    cache_read_per_1k=pricing_row.cache_read_price_per_1k,
                )
                if pricing_row
                else None
            ),
            pricing_id=str(pricing_row.id) if pricing_row else None,
        )

        if pricing_row is None:
            # 호출은 됩니다. 다만 비용이 0 으로 집계되므로 조용히 지나가면 안 됩니다.
            logger.warning("model.pricing_missing", alias=row.alias)

        await self._cache(redis, config)
        return self._ensure_active(config, model_ref)

    async def _latest_pricing(self, db: AsyncSession, alias: str):
        """지금 유효한 단가 1건.

        구간이 겹치지 않는 것은 DB 의 EXCLUDE 제약이 보장하므로 정렬 후 첫 행이면 충분합니다.
        """
        return (
            await db.execute(
                select(ModelPricingRow)
                .where(
                    and_(
                        ModelPricingRow.model_alias == alias,
                        ModelPricingRow.effective_from <= func.now(),
                        or_(
                            ModelPricingRow.effective_until.is_(None),
                            ModelPricingRow.effective_until > func.now(),
                        ),
                    )
                )
                .order_by(ModelPricingRow.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _cache(self, redis, config: ModelConfig) -> None:
        """alias 와 provider_model_id 두 키에 모두 채웁니다.

        client 가 어느 쪽으로 보내든 다음 요청이 한 번에 끝납니다. backend 는 alias 키를
        지우므로, provider_model_id 키는 TTL 로만 만료됩니다 — 그래서 두 키의 TTL 이 같습니다.
        """
        payload = config.to_dict()
        ttl = self._settings.policy_cache_ttl_seconds
        await cache.set_json(redis, cache_keys.model_policy(config.alias), payload, ttl)
        await cache.set_json(
            redis, cache_keys.model_policy(config.provider_model_id), payload, ttl
        )
