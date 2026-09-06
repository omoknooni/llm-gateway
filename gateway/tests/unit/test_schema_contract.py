"""매핑이 공유 계약의 읽기/쓰기 표면과 일치하는지 고정합니다.

실제 DB 없이 도는 테스트라 drift 를 전부 잡지는 못합니다(그건 통합 테스트의 몫). 여기서 잡는
것은 **우리가 무엇에 의존하기로 했는지**가 조용히 넓어지는 것입니다. 컬럼을 하나 더 매핑하면
그만큼 backend 스키마 변경에 더 묶입니다.
"""

from __future__ import annotations

import pytest

from gateway.schema import (
    AuthEvent,
    ModelAlias,
    ModelPricing,
    Team,
    TeamAllowedModel,
    UsageEvent,
    User,
    UserAllowedModel,
    VirtualKey,
    VirtualKeyAllowedModel,
)

EXPECTED = {
    Team: ("auth.teams", {"id", "is_active"}),
    User: ("auth.users", {"id", "team_id", "is_active"}),
    VirtualKey: (
        "auth.virtual_keys",
        {"id", "key_hash", "owner_type", "owner_id", "team_id", "status", "expires_at", "last_used_at"},
    ),
    VirtualKeyAllowedModel: ("auth.virtual_key_allowed_models", {"virtual_key_id", "model_alias"}),
    ModelAlias: (
        "model.model_aliases",
        {
            "alias", "display_name", "provider", "provider_model_id", "region", "endpoint_url",
            "supported_dialects", "status", "max_input_tokens", "max_output_tokens",
            "supports_streaming",
        },
    ),
    ModelPricing: (
        "model.model_pricings",
        {
            "id", "model_alias", "input_price_per_1k", "output_price_per_1k",
            "cache_write_price_per_1k", "cache_read_price_per_1k",
            "effective_from", "effective_until",
        },
    ),
    TeamAllowedModel: ("model.team_allowed_models", {"team_id", "model_alias"}),
    UserAllowedModel: ("model.user_allowed_models", {"user_id", "model_alias"}),
    UsageEvent: (
        "usage.usage_events",
        {
            "id", "request_id", "occurred_at", "team_id", "user_id", "virtual_key_id",
            "model_alias", "provider_model_id", "dialect", "status",
            "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
            "estimated_usage", "latency_ms", "ttft_ms", "is_streaming",
            "estimated_cost_usd", "pricing_id", "error_code", "client",
        },
    ),
    AuthEvent: (
        "usage.auth_events",
        {
            "id", "occurred_at", "first_occurred_at", "occurrence_count", "outcome",
            "virtual_key_id", "key_hash_prefix", "team_id", "user_id", "client",
            "model_alias", "source_ip", "request_id",
        },
    ),
}


@pytest.mark.parametrize("model", list(EXPECTED))
def test_mapped_surface(model):
    qualified, columns = EXPECTED[model]
    table = model.__table__
    assert f"{table.schema}.{table.name}" == qualified
    assert {c.name for c in table.columns} == columns


def test_audit_schema_is_not_mapped():
    """audit 은 control plane 의 것입니다. gateway 에는 GRANT 조차 없습니다."""
    from gateway.schema import Base

    assert all(t.schema != "audit" for t in Base.metadata.tables.values())


def test_no_ddl_helper_is_exposed():
    """create_all 을 부르는 코드가 이 저장소에 있으면 안 됩니다."""
    import pathlib

    src = pathlib.Path(__file__).parents[2] / "src"
    offenders = [p.name for p in src.rglob("*.py") if "create_all" in p.read_text()]
    assert offenders == []
