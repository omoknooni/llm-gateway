"""애플리케이션 설정. 환경변수에서만 읽습니다.

코드에 기본 시크릿을 두지 않습니다. 필수 설정이 없으면 조용히 기본값으로 뜨지 않고
기동에 실패합니다(`Settings.validate_runtime`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("ADMIN_EMAILS", "ADMIN_GROUPS", "ALLOWED_EMAIL_DOMAINS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """콤마 구분 문자열을 리스트로. `NoDecode` 로 기본 JSON 파싱을 껐기 때문에 필요합니다."""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # ── Application ──
    APP_NAME: str = "llm-gateway-admin-api"
    APP_ENV: str = "development"  # development | staging | production
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api/v1"

    # ── PostgreSQL ──
    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # ── Redis ──
    REDIS_URL: str = ""
    REDIS_POOL_SIZE: int = 20

    # ── 관리자 인증 ──
    # 로컬 개발 전용 토큰 경로. 운영에서 true 면 기동 시 거부합니다.
    DEV_LOGIN_ENABLED: bool = False

    # OIDC. ISSUER_URL 이 비어 있으면 OIDC 경로를 비활성화합니다.
    OIDC_ISSUER_URL: str = ""
    OIDC_AUDIENCE: str = ""
    OIDC_PROVIDER_NAME: str = "oidc"
    OIDC_JWKS_CACHE_TTL_SECONDS: int = 3600
    OIDC_DISCOVERY_URL_OVERRIDE: str = ""
    # claim 이름은 IdP 마다 다릅니다(예: Cognito 의 'cognito:groups').
    OIDC_USER_ID_CLAIM: str = "sub"
    OIDC_EMAIL_CLAIM: str = "email"
    OIDC_NAME_CLAIM: str = "name"
    OIDC_GROUPS_CLAIM: str = "groups"

    # 역할 부트스트랩. 이메일 또는 그룹이 매칭되면 ADMIN 을 부여합니다.
    ADMIN_EMAILS: Annotated[list[str], NoDecode] = []
    ADMIN_GROUPS: Annotated[list[str], NoDecode] = []

    #: 사용자 생성 시 허용할 이메일 도메인. 비어 있으면 검사하지 않습니다.
    ALLOWED_EMAIL_DOMAINS: Annotated[list[str], NoDecode] = []

    # ── 예산 ──
    #: Redis 카운터와 DB 내구 사본의 허용 차이(USD). data plane 의 UPSERT 지연분이 있어
    #: 0 으로 두면 정상 상태에서도 경고가 쏟아집니다.
    BUDGET_COUNTER_DRIFT_WARN_USD: float = 1.0

    # ── 사용량 집계 ──
    #: 재집계 시 되돌아볼 일수. gateway 가 이벤트를 메모리에 스풀했다가 쓰므로, 장애 복구 뒤
    #: 어제·그제 타임스탬프의 행이 새로 들어올 수 있습니다. 집계가 멱등해 다시 훑어도 됩니다.
    USAGE_AGGREGATION_LOOKBACK_DAYS: int = 3

    # ── Virtual Key ──
    VIRTUAL_KEY_ENV: str = "dev"  # 키 문자열에 박히는 환경 세그먼트 (live | dev)
    VIRTUAL_KEY_MAX_TTL_DAYS: int = 365
    VIRTUAL_KEY_MAX_ROTATION_GRACE_HOURS: int = 168

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def validate_runtime(self) -> None:
        """기동 시 호출. 실패하면 예외를 던져 프로세스를 죽입니다."""
        missing = [name for name in ("DATABASE_URL", "REDIS_URL") if not getattr(self, name)]
        if missing:
            raise RuntimeError(f"필수 설정이 비어 있습니다: {', '.join(missing)}")

        if self.is_production and self.DEV_LOGIN_ENABLED:
            raise RuntimeError("운영 환경에서 DEV_LOGIN_ENABLED 를 켤 수 없습니다")

        if self.VIRTUAL_KEY_ENV not in ("live", "dev"):
            raise RuntimeError("VIRTUAL_KEY_ENV 는 'live' 또는 'dev' 여야 합니다")


@lru_cache
def get_settings() -> Settings:
    return Settings()
