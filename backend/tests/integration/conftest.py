"""통합 테스트 공용 설비.

**SQLite 로 대체하지 않습니다**(07 문서). partial unique index, `EXCLUDE` 제약, enum, `citext`,
배열 컬럼, advisory lock, `percentile_disc` 가 전부 PostgreSQL 고유 기능이라 대체 DB 에서는
검증 가치가 없습니다.

스택이 없으면 **건너뜁니다.** 단위 테스트만 돌리는 환경에서 빨간 줄이 뜨면 아무도
`pytest` 를 안 쓰게 됩니다.

    ./scripts/test-stack.sh up      # 스택 기동 + 스키마 적용
    ./scripts/test-stack.sh test    # 전체 테스트
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/llm_gateway_test"
DEFAULT_REDIS_URL = "redis://localhost:56379/0"

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_DB_URL)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", DEFAULT_REDIS_URL)

#: 매 테스트 앞에서 비웁니다. `alembic_version` 은 남겨야 스키마가 살아 있습니다.
_TRUNCATE_SCHEMAS = ("auth", "model", "budget", "usage", "audit")

#: `0003` 부트스트랩이 만든 기본 팀. TRUNCATE 로 지워지므로 테스트가 직접 만듭니다.
BOOTSTRAP_TEAM = "platform"


def _configure_settings_env() -> None:
    """앱 설정을 테스트 스택으로 향하게 합니다. `get_settings` 가 lru_cache 라 캐시도 비웁니다."""
    os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
    os.environ.setdefault("REDIS_URL", TEST_REDIS_URL)
    os.environ.setdefault("DEV_LOGIN_ENABLED", "true")
    os.environ.setdefault("APP_ENV", "development")

    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(scope="session")
async def engine():
    _configure_settings_env()
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # 스택이 없으면 통합 테스트 전체를 건너뜁니다.
        await engine.dispose()
        pytest.skip(f"통합 테스트 스택이 없습니다 ({exc.__class__.__name__}). "
                    "`./scripts/test-stack.sh up` 후 다시 실행하세요", allow_module_level=True)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine):
    """추가 세션을 만드는 공장. 동시성 테스트가 **서로 다른 연결**을 써야 합니다."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def clean_db(engine):
    """테스트마다 빈 DB 에서 시작합니다.

    DROP/CREATE 가 아니라 TRUNCATE 입니다. 스키마를 다시 만들면 테스트마다 마이그레이션을
    돌리게 되고, 그러면 "마이그레이션이 적용되는가"와 "로직이 맞는가"가 한 테스트에 섞입니다.
    """
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables "
                "WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(_TRUNCATE_SCHEMAS)},
        )
        tables = [row[0] for row in rows]
        if tables:
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    return None


@pytest.fixture
async def db_session(engine, clean_db, session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
async def redis_client():
    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"Redis 테스트 스택이 없습니다 ({exc.__class__.__name__})")
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def cache_mgr(redis_client, session_factory):
    from app.core.cache_invalidation import CacheInvalidationManager

    return CacheInvalidationManager(redis_client, session_factory)


@pytest.fixture
def ctx():
    from app.core.deps import RequestContext

    return RequestContext(ip_address="127.0.0.1", request_id="test-request")


# ── 시드 헬퍼 ──


async def seed_team(session, name: str = "search-platform") -> uuid.UUID:
    from app.models.auth import Team

    team = Team(id=uuid.uuid4(), name=name, description="통합 테스트")
    session.add(team)
    await session.commit()
    return team.id


async def seed_user(
    session, team_id: uuid.UUID, *, email: str | None = None, role=None, display_name="tester"
) -> uuid.UUID:
    from app.models.auth import User
    from app.models.enums import UserRole

    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex[:12]}@example.com",
        display_name=display_name,
        role=role or UserRole.MEMBER,
        team_id=team_id,
        provider="test",
    )
    session.add(user)
    await session.commit()
    return user.id


async def seed_virtual_key(session, *, team_id: uuid.UUID, owner_id: uuid.UUID, created_by) -> uuid.UUID:
    from app.models.auth import VirtualKey
    from app.models.enums import VKOwnerType, VKStatus

    key = VirtualKey(
        id=uuid.uuid4(),
        name="integration-key",
        key_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        key_prefix="sk-test",
        owner_type=VKOwnerType.USER,
        owner_id=owner_id,
        team_id=team_id,
        status=VKStatus.ACTIVE,
        created_by=created_by,
    )
    session.add(key)
    await session.commit()
    return key.id


def admin_actor(user_id: uuid.UUID, team_id: uuid.UUID | None = None):
    from app.core.auth import CurrentAdmin
    from app.models.enums import UserRole

    return CurrentAdmin(
        user_id=user_id, email="admin@example.com", role=UserRole.ADMIN, team_id=team_id
    )


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)
