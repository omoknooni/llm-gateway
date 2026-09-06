"""async SQLAlchemy 엔진과 세션.

세션은 요청 스코프 의존성으로 주입하고, 백그라운드 작업은 `session_scope()` 를 씁니다.
트랜잭션 경계의 소유자는 service 계층입니다(00 문서).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    settings = get_settings()
    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        create_engine()
    assert _session_factory is not None
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 요청 스코프 의존성. 커밋은 service 가 합니다."""
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


#: 라우터에서 쓰는 요청 스코프 세션 의존성.
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
