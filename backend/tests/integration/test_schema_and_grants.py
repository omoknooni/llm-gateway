"""마이그레이션 적용 결과와 권한 경계 (M2 DoD).

"마이그레이션이 빈 DB 에 적용되고, 재적용이 멱등하다"와 "gateway_app 역할로 audit 스키마
접근이 거부된다"는 M2 부터 미검증으로 남아 있던 항목입니다.

여기서는 **적용된 결과**를 확인합니다. 적용 자체는 `scripts/test-stack.sh migrate` 가 하고,
그 스크립트가 두 번 돌아도 실패하지 않는 것이 멱등성 확인입니다.
"""

from __future__ import annotations

from sqlalchemy import text


async def test_all_domain_schemas_exist(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('auth','model','budget','usage','audit') ORDER BY 1"
            )
        )
    assert [row[0] for row in rows] == ["audit", "auth", "budget", "model", "usage"]


async def test_migration_is_at_head(engine):
    """`0005` 가 마지막 리비전입니다. 새 리비전을 넣으면 이 테스트가 알려줍니다."""
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert version == "0005"


async def test_required_extensions_are_installed(engine):
    """citext 는 이메일 유일성, btree_gist 는 단가 구간 겹침 차단(EXCLUDE)에 필요합니다."""
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname IN ('citext','btree_gist') ORDER BY 1")
        )
    assert [row[0] for row in rows] == ["btree_gist", "citext"]


async def test_gateway_app_cannot_touch_audit_schema(engine):
    """감사 로그는 control plane 의 것입니다. data plane 에 노출하지 않습니다(08 문서 C4)."""
    async with engine.connect() as conn:
        allowed = (
            await conn.execute(text("SELECT has_schema_privilege('gateway_app','audit','USAGE')"))
        ).scalar_one()
    assert allowed is False


async def test_gateway_app_writes_events_but_not_policy(engine):
    """gateway 는 정책을 **읽어 집행만** 합니다. 정의하지 않습니다."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT "
                    "  has_table_privilege('gateway_app','usage.usage_events','INSERT') AS ev_insert,"
                    "  has_table_privilege('gateway_app','usage.auth_events','INSERT') AS auth_insert,"
                    "  has_table_privilege('gateway_app','budget.budget_usages','UPDATE') AS usage_upd,"
                    "  has_table_privilege('gateway_app','auth.virtual_keys','SELECT') AS vk_read,"
                    "  has_table_privilege('gateway_app','auth.virtual_keys','INSERT') AS vk_write,"
                    "  has_table_privilege('gateway_app','budget.budget_configs','UPDATE') AS cfg_write"
                )
            )
        ).one()

    assert row.ev_insert and row.auth_insert and row.usage_upd and row.vk_read
    # 키를 발급하거나 예산을 정의할 수는 없습니다.
    assert not row.vk_write
    assert not row.cfg_write


async def test_gateway_app_can_update_only_last_used_at(engine):
    """컬럼 단위 GRANT 입니다. 키 상태를 gateway 가 바꿀 수 있으면 폐기가 무의미해집니다."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT "
                    "  has_column_privilege('gateway_app','auth.virtual_keys',"
                    "     'last_used_at','UPDATE') AS touch,"
                    "  has_column_privilege('gateway_app','auth.virtual_keys',"
                    "     'status','UPDATE') AS status_upd"
                )
            )
        ).one()
    assert row.touch
    assert not row.status_upd


async def test_backend_app_reads_events_and_writes_aggregates(engine):
    """원천은 gateway 가 쓰고 backend 가 읽습니다. 집계는 backend 가 씁니다(01 문서)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT "
                    "  has_table_privilege('backend_app','usage.usage_events','SELECT') AS ev_read,"
                    "  has_table_privilege('backend_app','usage.usage_events','INSERT') AS ev_write,"
                    "  has_table_privilege('backend_app','usage.auth_events','INSERT') AS auth_write,"
                    "  has_table_privilege('backend_app',"
                    "     'usage.daily_usage_aggregates','INSERT') AS agg_write,"
                    "  has_table_privilege('backend_app','audit.audit_logs','INSERT') AS audit_write"
                )
            )
        ).one()

    assert row.ev_read and row.agg_write and row.audit_write
    assert not row.ev_write
    assert not row.auth_write


async def test_partial_unique_index_on_active_budget_config(engine):
    """활성 예산 설정이 scope 당 하나인 것은 **DB 제약**입니다.

    서비스가 "닫고 넣기"를 지키지 않으면 여기서 막혀야 합니다. SQLite 로 대체할 수 없는
    이유 중 하나입니다.
    """
    async with engine.connect() as conn:
        indexdef = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname='budget' AND indexname='uq_budget_config_active'"
                )
            )
        ).scalar_one()
    assert "UNIQUE" in indexdef
    assert "WHERE is_active" in indexdef
