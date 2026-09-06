"""PostgreSQL 연결.

역할은 `gateway_app` 입니다. 정책을 읽어 집행만 하고 스키마를 정의하지 않으므로 이 패키지에
Alembic 이 없습니다. 스키마의 단일 소유자는 backend 입니다.

**요청 전 구간에 세션을 잡지 않습니다.** 각 소비자가 필요한 시점에 short-lived 세션을 열고
즉시 닫습니다. SSE 응답 동안 세션을 들고 있으면 커넥션이 `idle in transaction` 으로 묶여
풀이 회전하지 못합니다.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from gateway.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        # 죽은 커넥션(RDS Proxy 유휴 절단)이 풀에 남는 것을 1차로 막습니다.
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
