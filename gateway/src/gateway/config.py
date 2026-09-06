"""설정.

값은 환경변수에서만 옵니다. 코드에 CSP 별·환경별 분기를 두지 않고, 환경 차이는 여기의
설정값으로만 표현합니다(docs/05). AWS 자격 증명은 이 파일에 없습니다 — 기본 credential
chain 에 위임하므로 운영(IRSA)과 로컬(개발자 프로필)이 같은 코드로 동작합니다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 분류 규칙이 어떻게 바뀌어도 반드시 존재해야 하는 예약어. 설정으로 지울 수 없습니다.
CLIENT_OTHER = "other"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_format: str = "json"

    # ── PostgreSQL (역할: gateway_app) ──
    database_url: str = "postgresql+asyncpg://gateway_app:gateway_app@localhost:5432/llm_gateway"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    #: 풀 고갈 시 30초를 기다리면 "CPU 는 정상인데 느림"이 됩니다. 짧게 끊어 fast-fail 합니다.
    db_pool_timeout: int = 10
    #: RDS Proxy 가 유휴 커넥션을 끊으면 죽은 커넥션이 풀에 남습니다. pre_ping 과 함께 씁니다.
    db_pool_recycle: int = 3600

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"
    #: 명령 상한. 없으면(None) 느린 노드 하나가 풀 전체를 무한 대기로 묶습니다.
    redis_socket_timeout: float = 2.0
    redis_connect_timeout: float = 1.0
    redis_health_check_interval: float = 30.0

    # ── 캐시 TTL (docs/README 의 Redis 키 규약) ──
    #: 무효화 실패의 영향이 "영구 불일치"가 아니라 "TTL 만큼의 반영 지연"에 머물게 하는 상한.
    vk_auth_ttl_seconds: int = 300
    policy_cache_ttl_seconds: int = 300
    vk_miss_ttl_seconds: int = 30

    # ── AWS ──
    aws_region: str = "ap-northeast-2"
    #: boto3 는 동기라 전용 스레드 풀에서 돌립니다. 이 값이 동시 스트림 수의 상한입니다.
    bedrock_thread_pool_size: int = 128
    #: gateway 가 자체 재시도를 소유합니다. botocore 재시도와 곱해지면 장애 시 요청 폭풍이 됩니다.
    bedrock_max_attempts: int = 1

    # ── 요청 한도와 타임아웃 (docs/01) ──
    max_body_size: int = 20 * 1024 * 1024
    stream_timeout: int = 300
    #: ALB idle timeout 보다 **작아야** 합니다. 크면 ALB 가 먼저 끊어 잘린 스트림이 됩니다.
    stream_idle_timeout: int = 240
    stream_disconnect_drain_timeout: int = 30
    #: model_aliases.max_output_tokens 도 NULL 일 때만 쓰는 최후 기본값.
    default_max_output_tokens: int = 4096

    # ── client 식별 (docs/03) ──
    registered_clients: str = "claude-code,claude-desktop,codex,openai-sdk"

    # ── 기록 ──
    last_used_throttle_seconds: int = 60
    auth_event_window_seconds: int = 60
    usage_spool_max: int = 10_000

    @field_validator("log_format")
    @classmethod
    def _check_log_format(cls, v: str) -> str:
        if v not in ("json", "console"):
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        return v

    @property
    def registered_client_set(self) -> frozenset[str]:
        """설정에 무엇이 오든 예약어 'other' 는 항상 포함됩니다."""
        values = {c.strip() for c in self.registered_clients.split(",") if c.strip()}
        return frozenset(values | {CLIENT_OTHER})


@lru_cache
def get_settings() -> Settings:
    return Settings()
