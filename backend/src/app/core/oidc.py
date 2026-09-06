"""OIDC 토큰 검증.

discovery 문서에서 JWKS 를 받아 서명을 검증합니다. JWKS 는 TTL 캐시하고, 모르는 `kid` 를
만나면 한 번 강제 갱신합니다(키 로테이션 대응). 갱신에는 최소 간격을 둬 IdP 를 두드리지
않게 합니다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog
from jose import JWTError, jwt

from app.core.clock import utcnow
from app.core.exceptions import UnauthenticatedError

logger = structlog.get_logger()

#: 모르는 kid 를 만났을 때 JWKS 를 다시 받아오는 최소 간격(초).
_FORCED_REFRESH_MIN_INTERVAL = 60.0


class OIDCVerifier:
    def __init__(
        self,
        *,
        issuer_url: str,
        audience: str = "",
        jwks_cache_ttl_seconds: int = 3600,
        discovery_url_override: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._issuer_url = issuer_url.rstrip("/")
        self._audience = audience
        self._ttl = jwks_cache_ttl_seconds
        self._discovery_base = (discovery_url_override or issuer_url).rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=10.0)
        self._owns_http = http_client is None

        self._jwks: dict[str, dict[str, Any]] = {}
        self._jwks_fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def verify(self, token: str) -> dict[str, Any]:
        """검증에 성공하면 claim 딕셔너리를 반환합니다."""
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise UnauthenticatedError("토큰 형식이 올바르지 않습니다") from exc

        kid = header.get("kid")
        key = await self._resolve_key(kid)
        if key is None:
            raise UnauthenticatedError("토큰 서명 키를 찾을 수 없습니다")

        options = {"verify_aud": bool(self._audience)}
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[header.get("alg", "RS256")],
                issuer=self._issuer_url,
                audience=self._audience or None,
                options=options,
            )
        except JWTError as exc:
            raise UnauthenticatedError("토큰 검증에 실패했습니다") from exc

    async def _resolve_key(self, kid: str | None) -> dict[str, Any] | None:
        keys = await self._get_jwks()
        if kid is None:
            # kid 가 없으면 키가 하나일 때만 확정할 수 있습니다.
            return next(iter(keys.values())) if len(keys) == 1 else None
        if kid in keys:
            return keys[kid]

        # 키 로테이션 가능성 → 한 번만 강제 갱신.
        keys = await self._get_jwks(force=True)
        return keys.get(kid)

    async def _get_jwks(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        now = utcnow().timestamp()
        fresh = self._jwks and (now - self._jwks_fetched_at) < self._ttl
        if fresh and not force:
            return self._jwks
        if force and (now - self._jwks_fetched_at) < _FORCED_REFRESH_MIN_INTERVAL:
            return self._jwks

        async with self._lock:
            # 락을 기다리는 동안 다른 태스크가 갱신했을 수 있습니다.
            now = utcnow().timestamp()
            if self._jwks and (now - self._jwks_fetched_at) < _FORCED_REFRESH_MIN_INTERVAL:
                return self._jwks
            await self._fetch_jwks()
        return self._jwks

    async def _fetch_jwks(self) -> None:
        discovery_url = f"{self._discovery_base}/.well-known/openid-configuration"
        try:
            discovery = (await self._http.get(discovery_url)).raise_for_status().json()
            jwks_uri = discovery["jwks_uri"]
            payload = (await self._http.get(jwks_uri)).raise_for_status().json()
        except Exception as exc:
            logger.error("oidc.jwks_fetch_failed", discovery_url=discovery_url, error=str(exc))
            raise UnauthenticatedError("IdP 키를 가져오지 못했습니다") from exc

        self._jwks = {key["kid"]: key for key in payload.get("keys", []) if "kid" in key}
        self._jwks_fetched_at = utcnow().timestamp()
        logger.info("oidc.jwks_loaded", key_count=len(self._jwks))
