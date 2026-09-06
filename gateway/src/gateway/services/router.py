"""요청 하나를 어떤 모델·provider·리전으로 보낼지 결정합니다.

    1. model   ← alias 해석 (Redis → DB)
    2. ScopeCheck → 방언 호환성 검사
    3. provider ← model.provider          카탈로그가 결정한다
    4. region   ← model.region ?? 배포 기본 리전
    5. call_model_id ← 리전 접두사 재작성

3번이 핵심입니다. 어떤 provider 를 쓸지는 모델 카탈로그가 결정합니다. 다른 축이 provider 를
바꾸면 같은 alias 가 상황에 따라 다른 백엔드로 가서, 단가 테이블과 실제 호출이 어긋납니다.

검사 순서도 계약입니다. ScopeCheck 는 **모델 해석 이후, 호출 이전**입니다. 해석보다 앞서면
존재하지 않는 모델에 403 을 주게 됩니다.

ScopeCheck 를 방언 검사보다 **먼저** 합니다. 허용되지 않은 키는 어떻게 물어보든 같은 답(403)을
받아야 합니다. 방언 검사가 앞서면 권한 없는 키가 그 모델의 지원 방언을 알아낼 수 있습니다.
"""

from __future__ import annotations

import structlog

from gateway.config import Settings
from gateway.core.context import AuthContext
from gateway.core.dialect import ApiDialect
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.core.routing import BackendDecision
from gateway.services.model_resolver import ModelResolver
from gateway.services.region import rewrite_model_id

logger = structlog.get_logger(__name__)


class Router:
    def __init__(self, settings: Settings, resolver: ModelResolver) -> None:
        self._settings = settings
        self._resolver = resolver

    async def decide(
        self,
        *,
        model_ref: str,
        dialect: ApiDialect,
        auth: AuthContext,
        stream: bool,
        redis,
        session_factory,
    ) -> BackendDecision:
        model = await self._resolver.resolve(
            model_ref=model_ref, redis=redis, session_factory=session_factory
        )

        # 비교는 alias 하나로만 합니다. 허용 목록에는 alias 만 들어 있고, 해석된 모델을
        # 기준으로 보므로 client 가 provider_model_id 로 요청해도 같은 판정이 나옵니다.
        # 요청 문자열로 비교하면 같은 모델을 다른 이름으로 불러 우회할 수 있습니다.
        if model.alias not in auth.allowed_model_aliases:
            logger.info(
                "router.model_not_allowed",
                alias=model.alias,
                virtual_key_id=auth.virtual_key_id,
            )
            raise GatewayError(
                ErrorCode.MODEL_NOT_ALLOWED,
                f"Model '{model.alias}' is not allowed for this key",
                param="model",
                outcome=AuthOutcome.MODEL_NOT_ALLOWED,
                model_alias=model.alias,
            )

        if not model.supports(dialect):
            # 대안 엔드포인트를 알려줘야 client 가 스스로 고칠 수 있습니다.
            other = (
                "/v1/chat/completions"
                if dialect is ApiDialect.ANTHROPIC_MESSAGES
                else "/v1/messages"
            )
            raise GatewayError(
                ErrorCode.DIALECT_NOT_SUPPORTED,
                f"Model '{model.alias}' is not available on this endpoint. "
                f"Supported: {', '.join(model.supported_dialects)} (try {other})",
                param="model",
            )

        if stream and not model.supports_streaming:
            raise GatewayError(
                ErrorCode.DIALECT_NOT_SUPPORTED,
                f"Model '{model.alias}' does not support streaming",
                param="stream",
            )

        region = model.region or self._settings.aws_region
        return BackendDecision(
            model=model,
            provider=model.provider,
            call_model_id=rewrite_model_id(model.provider_model_id, region),
            region=region,
            endpoint_url=model.endpoint_url,
        )
