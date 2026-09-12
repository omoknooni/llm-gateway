"""PostgreSQL advisory lock.

두 종류를 둡니다.

- `advisory_lock` — **세션 스코프**. 주기 작업이 replica 여러 개에서 동시에 돌지 않게 합니다.
  잡지 못하면 건너뜁니다(기다리지 않습니다).
- `xact_lock` — **트랜잭션 스코프**. 요청 경로에서 같은 대상에 대한 쓰기를 직렬화합니다.
  커밋/롤백 시 자동으로 풀려 해제를 잊을 수 없습니다.
"""

from __future__ import annotations

import uuid
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

#: 두 정수 형식 advisory lock 의 앞 정수. 다른 애플리케이션·다른 용도와 섞이지 않게 합니다.
_NAMESPACE_BUDGET_TEAM = 0x4C4C4D31


def _lock_key(name: str) -> int:
    """작업 이름을 bigint 로. 다른 애플리케이션과 충돌하지 않도록 네임스페이스를 붙입니다."""
    return zlib.crc32(f"llm-gateway:{name}".encode()) - 2**31


def _uuid_key(value: uuid.UUID) -> int:
    """UUID 를 int4 로 접습니다.

    충돌하면 관계없는 두 팀이 서로를 기다립니다 — 느려질 뿐 틀리지 않습니다. 잠금 대상이
    팀 단위(저 QPS)라 이 정도 접기로 충분합니다.
    """
    return zlib.crc32(value.bytes) - 2**31


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


async def lock_team_budget(session: AsyncSession, team_id: uuid.UUID) -> None:
    """팀 예산 변경을 직렬화합니다. 커밋/롤백까지 유지됩니다.

    **행 잠금으로는 부족합니다.** 팀 예산 한도와 사용자 예산은 서로 다른 행이라,
    "현재 배분 합계를 읽고 → 다른 사용자 행을 INSERT" 하는 두 요청이 충돌 없이 둘 다
    커밋됩니다(write skew). 팀 한도 100 에 60 짜리 두 요청이 동시에 들어오면 합계가 120 이
    됩니다. 팀 예산 행이 아직 없는 경우도 있어 잠글 행 자체가 없을 수 있습니다.

    그래서 **팀 id 를 키로 한 advisory lock** 으로 묶습니다. 같은 팀의 예산 쓰기가 전부 이
    잠금을 지나면 합계 검증과 삽입이 원자적으로 보입니다.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :key)"),
        {"ns": _NAMESPACE_BUDGET_TEAM, "key": _uuid_key(team_id)},
    )
