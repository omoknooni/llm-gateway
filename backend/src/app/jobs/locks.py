"""주기 작업의 단일 실행 보장.

replica 가 여러 개면 같은 작업이 동시에 돌아 같은 행을 두 번 처리합니다.
PostgreSQL advisory lock 으로 한 번에 하나만 돌게 합니다. 세션이 끊기면 락도 풀리므로
프로세스가 죽어도 잠금이 남지 않습니다.
"""

from __future__ import annotations

import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def _lock_key(name: str) -> int:
    """작업 이름을 bigint 로. 다른 애플리케이션과 충돌하지 않도록 네임스페이스를 붙입니다."""
    return zlib.crc32(f"llm-gateway:{name}".encode()) - 2**31


@asynccontextmanager
async def advisory_lock(session: AsyncSession, name: str) -> AsyncIterator[bool]:
    """락을 잡으면 True 를 넘깁니다. 이미 누가 잡고 있으면 False 를 넘기고 건너뜁니다."""
    key = _lock_key(name)
    acquired = bool(
        (await session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})).scalar()
    )
    try:
        yield acquired
    finally:
        if acquired:
            await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
