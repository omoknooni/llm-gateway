"""Mantle bearer 토큰 발급.

Mantle 은 boto3 가 아니라 **HTTPS + Bearer** 로 부릅니다. 토큰은 pod 자신의 IRSA 자격에서
SigV4 로 만들어지며, 이 파일에도 장기 자격 증명이 없습니다.

두 가지가 계약입니다.

- **bearer 는 리전에 묶입니다.** SigV4 가 리전 엔드포인트에 서명하므로 리전이 다르면 다른
  토큰이어야 합니다. 캐시 키가 리전을 빠뜨리면 교차 사용으로 401 이 납니다.
- **bearer 는 자신을 만든 자격보다 오래 살 수 없습니다.** 자격 만료 직전으로 상한을 겁니다.

cross-account 는 이번 범위 밖입니다(role ARN 을 둘 자리가 backend 스키마에 없습니다 —
docs/05). 캐시 키를 지금부터 튜플로 두어 그 확장이 구조를 바꾸지 않게 합니다.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

#: 자격은 IRSA 가 주기적으로 갱신합니다. 그보다 훨씬 짧게 재발급해 회전을 따라갑니다.
BEARER_TTL_SECONDS = 1800
#: 자격 만료 직전에 만든 토큰이 곧바로 죽는 것을 막는 여유.
CREDENTIAL_SKEW_SECONDS = 60
#: IRSA 자격의 통상 수명. 정확한 만료를 알 수 없을 때의 보수적 가정입니다.
ASSUMED_CREDENTIAL_TTL = 3600


@dataclass
class _CachedBearer:
    #: repr 에 담기지 않게 합니다. 예외 메시지나 디버깅 출력으로 새는 경로를 막습니다.
    token: str = field(repr=False)
    expires_at: float = 0.0


class MantleCredentialBroker:
    def __init__(self, session_factory=None, token_generator=None, now=time.monotonic) -> None:
        self._session_factory = session_factory
        self._token_generator = token_generator
        self._now = now
        #: (자격 키, 리전) → 토큰. cross-account 가 열리면 자격 키가 role ARN 이 됩니다.
        self._cache: dict[tuple[str, str], _CachedBearer] = {}
        self._lock = asyncio.Lock()

    async def bearer_token(self, region: str) -> str:
        key = ("in-account", region)
        async with self._lock:
            cached = self._cache.get(key)
            now = self._now()
            if cached and cached.expires_at > now:
                return cached.token

            token = await asyncio.get_running_loop().run_in_executor(
                None, self._mint, region
            )
            self._cache[key] = _CachedBearer(
                token=token,
                expires_at=now + min(
                    BEARER_TTL_SECONDS, ASSUMED_CREDENTIAL_TTL - CREDENTIAL_SKEW_SECONDS
                ),
            )
            logger.info("mantle.bearer_minted", region=region)
            return token

    def _mint(self, region: str) -> str:
        """동기 SDK 호출이라 executor 에서 실행됩니다."""
        generator = self._token_generator or _default_generator()
        session = (self._session_factory or _default_session)()
        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError(
                "No AWS credentials available for Mantle. Ensure IRSA is configured on the pod."
            )
        return generator(credentials.get_frozen_credentials(), region)


def _default_session():
    import boto3

    return boto3.Session()


def _default_generator():
    """지연 import.

    Mantle 을 쓰지 않는 배포에서는 이 의존성이 없어도 gateway 가 뜹니다. 실제로 필요할 때만
    분명한 메시지로 실패합니다.
    """
    try:
        from aws_bedrock_token_generator import BedrockTokenGenerator
    except ImportError as exc:  # pragma: no cover - 의존성이 없을 때만
        raise RuntimeError(
            "aws-bedrock-token-generator is required for the Mantle backend"
        ) from exc

    generator = BedrockTokenGenerator()
    return lambda credentials, region: generator.get_token(credentials, region)
