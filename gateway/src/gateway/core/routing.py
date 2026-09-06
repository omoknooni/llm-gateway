"""라우팅 결정.

`BackendDecision` 은 "어떤 모델을, 어떤 provider 로, 어느 리전에서" 부를지에 대한 답이며,
provider adapter 는 이것만 받아 호출합니다. adapter 가 설정이나 DB 를 다시 읽을 일이 없어야
합니다(docs/04).
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway.core.model import ModelConfig


@dataclass(frozen=True)
class BackendDecision:
    model: ModelConfig
    provider: str
    #: 리전 접두사 재작성이 끝난 최종 모델 ID.
    call_model_id: str
    region: str
    endpoint_url: str | None
