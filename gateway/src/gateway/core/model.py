"""해석된 모델 설정.

`model.model_aliases` 한 행이 provider, 모델 id, 리전, 엔드포인트, 지원 방언, 단가를 전부
갖고 있습니다. 라우팅은 그 행을 찾아 읽는 일이지 여러 축을 합성하는 일이 아닙니다(docs/04).

`policy:model:{alias}` 에 그대로 직렬화됩니다. 금액은 문자열로 실어 `Decimal` 로 복원합니다 —
부동소수점을 거치면 단가의 유효숫자가 조용히 깎입니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from gateway.core.dialect import ApiDialect


@dataclass(frozen=True)
class ModelPricing:
    input_per_1k: Decimal
    output_per_1k: Decimal
    cache_write_per_1k: Decimal
    cache_read_per_1k: Decimal

    def to_dict(self) -> dict[str, str]:
        return {
            "input_per_1k": str(self.input_per_1k),
            "output_per_1k": str(self.output_per_1k),
            "cache_write_per_1k": str(self.cache_write_per_1k),
            "cache_read_per_1k": str(self.cache_read_per_1k),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ModelPricing:
        return cls(
            input_per_1k=Decimal(data["input_per_1k"]),
            output_per_1k=Decimal(data["output_per_1k"]),
            cache_write_per_1k=Decimal(data["cache_write_per_1k"]),
            cache_read_per_1k=Decimal(data["cache_read_per_1k"]),
        )


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    provider: str
    provider_model_id: str
    #: NULL 이면 배포 기본 리전.
    region: str | None
    #: Mantle 계열만 사용합니다.
    endpoint_url: str | None
    supported_dialects: tuple[str, ...]
    status: str
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_streaming: bool
    #: 단가 행이 없을 수 있습니다. 그때도 호출은 되고 비용만 0 으로 기록됩니다.
    pricing: ModelPricing | None
    #: 어떤 단가로 계산했는지 usage_events.pricing_id 에 그대로 실립니다.
    pricing_id: str | None

    def supports(self, dialect: ApiDialect) -> bool:
        return dialect.value in self.supported_dialects

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "provider": self.provider,
            "provider_model_id": self.provider_model_id,
            "region": self.region,
            "endpoint_url": self.endpoint_url,
            "supported_dialects": list(self.supported_dialects),
            "status": self.status,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "pricing": self.pricing.to_dict() if self.pricing else None,
            "pricing_id": self.pricing_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ModelConfig:
        pricing = data.get("pricing")
        return cls(
            alias=data["alias"],
            provider=data["provider"],
            provider_model_id=data["provider_model_id"],
            region=data.get("region"),
            endpoint_url=data.get("endpoint_url"),
            supported_dialects=tuple(data["supported_dialects"]),
            status=data["status"],
            max_input_tokens=data.get("max_input_tokens"),
            max_output_tokens=data.get("max_output_tokens"),
            supports_streaming=data["supports_streaming"],
            pricing=ModelPricing.from_dict(pricing) if pricing else None,
            pricing_id=data.get("pricing_id"),
        )
