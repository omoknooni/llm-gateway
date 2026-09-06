from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer

from app.models.enums import ApiDialect, ModelStatus, Provider
from app.policy.allowed_models import ResolvedFrom


class PricingCreateRequest(BaseModel):
    input_price_per_1k: Decimal = Field(gt=0, description="1k 입력 토큰당 USD")
    output_price_per_1k: Decimal = Field(gt=0, description="1k 출력 토큰당 USD")
    cache_write_price_per_1k: Decimal = Field(default=Decimal("0"), ge=0)
    cache_read_price_per_1k: Decimal = Field(default=Decimal("0"), ge=0)
    effective_from: datetime
    source: str = Field(default="MANUAL", max_length=32)


class PricingResponse(BaseModel):
    id: str
    model_alias: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    cache_write_price_per_1k: Decimal
    cache_read_price_per_1k: Decimal
    currency: str
    effective_from: datetime
    effective_until: datetime | None
    source: str

    @field_serializer(
        "input_price_per_1k",
        "output_price_per_1k",
        "cache_write_price_per_1k",
        "cache_read_price_per_1k",
    )
    def _money_as_string(self, value: Decimal) -> str:
        """금액은 문자열로 직렬화합니다. JSON number 로 내보내면 프론트에서 정밀도가 깨집니다."""
        return str(value)


class ModelCreateRequest(BaseModel):
    alias: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9.-]{1,127}$")
    display_name: str | None = None
    provider: Provider = Provider.BEDROCK
    provider_model_id: str = Field(min_length=1, max_length=512)
    region: str | None = None
    supported_dialects: list[ApiDialect] = Field(min_length=1)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supports_streaming: bool = True
    description: str | None = None
    #: 단가 없이 ACTIVE 가 되면 비용이 0 으로 집계되어 관제 목적을 무너뜨립니다.
    pricing: PricingCreateRequest


class ModelUpdateRequest(BaseModel):
    display_name: str | None = None
    provider_model_id: str | None = Field(default=None, min_length=1, max_length=512)
    region: str | None = None
    supported_dialects: list[ApiDialect] | None = Field(default=None, min_length=1)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supports_streaming: bool | None = None
    description: str | None = None


class ModelStatusRequest(BaseModel):
    status: ModelStatus


class ModelResponse(BaseModel):
    alias: str
    display_name: str | None
    provider: Provider
    provider_model_id: str
    region: str | None
    supported_dialects: list[ApiDialect]
    status: ModelStatus
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_streaming: bool
    description: str | None
    current_pricing: PricingResponse | None = None
    created_at: datetime
    updated_at: datetime


class AllowedModelsRequest(BaseModel):
    #: 전체 교체. 빈 배열의 의미는 층마다 다릅니다(04 문서).
    model_aliases: list[str]


class AllowedModelsResponse(BaseModel):
    scope: str
    scope_id: str
    model_aliases: list[str]


class EffectiveModelsResponse(BaseModel):
    user_id: str
    model_aliases: list[str]
    resolved_from: ResolvedFrom
    narrowed_by_key: bool = False
