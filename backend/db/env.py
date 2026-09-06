"""Alembic 환경 설정.

DB URL 은 `MIGRATION_DATABASE_URL` 로 주입합니다. 런타임 역할(`backend_app`)에는
DDL 권한이 없으므로, 마이그레이션은 별도 역할로 실행합니다(01 문서).
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.models.base import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 이 컴포넌트가 관리하는 스키마. 여기 없는 스키마의 객체는 autogenerate 대상이 아닙니다.
MANAGED_SCHEMAS = {"auth", "model", "budget", "usage", "audit"}


def _database_url() -> str:
    url = os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL (또는 DATABASE_URL) 이 필요합니다")
    return url


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    schema = getattr(obj, "schema", None)
    return not (type_ == "table" and schema not in MANAGED_SCHEMAS)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
        # online 경로와 같은 이유(0004 의 enum 값을 0005 가 씁니다). offline 스크립트도
        # 리비전마다 BEGIN/COMMIT 이 나뉘어야 한 번에 실행됩니다.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        # 리비전마다 트랜잭션을 분리합니다. PostgreSQL 은 `ALTER TYPE ... ADD VALUE` 로 추가한
        # enum 값을 같은 트랜잭션에서 쓰지 못하므로, 값 추가(0004)와 사용(0005)이 한 트랜잭션에
        # 묶이면 upgrade 가 실패합니다.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", _database_url())
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
