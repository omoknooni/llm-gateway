from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..config import settings
from ..models import ModelAlias, VirtualKey


@dataclass
class LiteLLMSyncResult:
    synced: bool
    keys_pushed: int
    aliases_seen: int
    detail: str


class LiteLLMAdminClient:
    def __init__(self) -> None:
        self.base_url = settings.litellm_admin_url.rstrip("/")
        self.master_key = settings.litellm_master_key
        self.enabled = settings.litellm_sync_enabled

    async def sync_all(
        self,
        keys: list[VirtualKey],
        aliases: list[ModelAlias],
    ) -> LiteLLMSyncResult:
        if not self.enabled:
            return LiteLLMSyncResult(
                synced=False,
                keys_pushed=len(keys),
                aliases_seen=len(aliases),
                detail="LiteLLM sync disabled; returning dry-run summary only.",
            )

        headers = {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            for key in keys:
                payload = {
                    "key": key.secret_value,
                    "key_alias": key.masked_key,
                    "duration": None,
                    "models": key.allowed_model_aliases,
                    "metadata": {
                        "owner_type": key.owner_type,
                        "team_id": key.team_id,
                        "user_id": key.user_id,
                        "source_record_id": key.id,
                    },
                }
                response = await client.post(f"{self.base_url}/key/generate", headers=headers, json=payload)
                response.raise_for_status()

        return LiteLLMSyncResult(
            synced=True,
            keys_pushed=len(keys),
            aliases_seen=len(aliases),
            detail="Active keys pushed to LiteLLM Admin API.",
        )


litellm_admin_client = LiteLLMAdminClient()
