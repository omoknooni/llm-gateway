"""정책 거절 기록 (`usage.auth_events`).

provider 호출이 없었던 거절(401/403/429)은 `usage_events` 가 아니라 여기로 갑니다. 토큰도
비용도 0 인 행을 집계 테이블에 쌓으면 모든 대시보드 쿼리가 그것을 걸러내야 합니다(docs/06 S4).

동일 출처의 연속 실패는 창(window) 하나로 묶어 한 행만 씁니다. 실패마다 INSERT 하면 공격
트래픽이 그대로 DB 부하가 됩니다. 대신 행 하나가 N 건을 대표하므로 **조회는 행 수가 아니라
`SUM(occurrence_count)`** 여야 합니다 — 창이 프로세스 로컬이라 pod 수만큼 행이 나뉩니다.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.core.clock import utcnow
from gateway.schema.usage import AuthEvent

logger = structlog.get_logger(__name__)


@dataclass
class _Window:
    #: 창의 첫 요청 id. 그 요청의 로그 줄이 원인을 담고 있어 조사 진입점이 됩니다.
    request_id: str
    first_occurred_at: datetime
    occurred_at: datetime
    count: int = 1
    opened_at: float = field(default_factory=time.monotonic)
    virtual_key_id: str | None = None
    team_id: str | None = None
    user_id: str | None = None
    model_alias: str | None = None


class AuthEventRecorder:
    def __init__(self, window_seconds: int) -> None:
        self._window_seconds = window_seconds
        #: 묶음 키 = (outcome, key_hash_prefix, source_ip, client)
        self._windows: dict[tuple[str | None, ...], _Window] = {}

    def observe(
        self,
        *,
        outcome: str,
        request_id: str,
        key_hash_prefix: str | None = None,
        source_ip: str | None = None,
        client: str | None = None,
        virtual_key_id: str | None = None,
        team_id: str | None = None,
        user_id: str | None = None,
        model_alias: str | None = None,
    ) -> None:
        key = (outcome, key_hash_prefix, source_ip, client)
        window = self._windows.get(key)
        now = utcnow()
        if window is None:
            self._windows[key] = _Window(
                request_id=request_id,
                first_occurred_at=now,
                occurred_at=now,
                virtual_key_id=virtual_key_id,
                team_id=team_id,
                user_id=user_id,
                model_alias=model_alias,
            )
            return
        window.count += 1
        window.occurred_at = now

    def pop_expired(self, *, force: bool = False) -> list[dict]:
        """닫힌 창을 행으로 바꿔 돌려줍니다. `force` 는 종료 시 전부 비웁니다."""
        now = time.monotonic()
        rows: list[dict] = []
        for key in list(self._windows):
            window = self._windows[key]
            if not force and now - window.opened_at < self._window_seconds:
                continue
            outcome, key_hash_prefix, source_ip, client = key
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "occurred_at": window.occurred_at,
                    "first_occurred_at": window.first_occurred_at,
                    "occurrence_count": window.count,
                    "outcome": outcome,
                    "virtual_key_id": window.virtual_key_id,
                    "key_hash_prefix": key_hash_prefix,
                    "team_id": window.team_id,
                    "user_id": window.user_id,
                    "client": client,
                    "model_alias": window.model_alias,
                    "source_ip": source_ip,
                    "request_id": window.request_id,
                }
            )
            del self._windows[key]
        return rows

    async def flush(
        self, session_factory: async_sessionmaker[AsyncSession] | None, *, force: bool = False
    ) -> int:
        rows = self.pop_expired(force=force)
        if not rows or session_factory is None:
            # DB 가 없으면 기록을 버립니다. 거절 감사는 usage 기록과 달리 과금에 영향을 주지
            # 않으므로, 장애 중에 메모리를 붙들고 있을 이유가 없습니다.
            if rows:
                logger.warning("auth_event.dropped_no_database", count=len(rows))
            return 0
        try:
            async with session_factory() as db:
                await db.execute(AuthEvent.__table__.insert(), rows)
                await db.commit()
        except Exception as exc:
            logger.warning("auth_event.flush_failed", error=str(exc), count=len(rows))
            return 0
        return len(rows)
