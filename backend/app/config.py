from __future__ import annotations

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    app_name: str = "LiteLLM Gateway Control Plane"
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite+pysqlite:///./llm_gateway.db",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    local_admin_username: str = os.getenv("LOCAL_ADMIN_USERNAME", "admin")
    local_admin_password: str = os.getenv("LOCAL_ADMIN_PASSWORD", "admin123!")
    local_admin_token: str = os.getenv("LOCAL_ADMIN_TOKEN", "dev-admin-token")
    cors_origins: list[str] = None  # type: ignore[assignment]
    litellm_admin_url: str = os.getenv("LITELLM_ADMIN_URL", "http://localhost:4000")
    litellm_master_key: str = os.getenv("LITELLM_MASTER_KEY", "sk-litellm-master")
    litellm_sync_enabled: bool = os.getenv("LITELLM_SYNC_ENABLED", "false").lower() == "true"
    bedrock_region: str = os.getenv("BEDROCK_AWS_REGION", "us-east-1")
    bedrock_model_claude_sonnet_id: str = os.getenv(
        "BEDROCK_MODEL_CLAUDE_SONNET_ID",
        "anthropic.claude-3-5-sonnet-v2-placeholder",
    )
    bedrock_model_claude_haiku_id: str = os.getenv(
        "BEDROCK_MODEL_CLAUDE_HAIKU_ID",
        "anthropic.claude-3-haiku-placeholder",
    )

    def __post_init__(self) -> None:
        if self.cors_origins is None:
            self.cors_origins = _split_csv(os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:3000"))


settings = Settings()

