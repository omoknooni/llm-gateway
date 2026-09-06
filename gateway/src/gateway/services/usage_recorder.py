"""사용량 기록.

**gateway 가 `usage.usage_events` 에 직접 INSERT 합니다.** 응답을 반환한 뒤 백그라운드로 쓰고,
실패하면 메모리 스풀에 넣어 재시도합니다. Redis Stream + 별도 worker 는 채택하지 않았습니다 —
컴포넌트가 하나 늘고 소유자가 불분명해지는 대가에 비해 얻는 것이 크지 않습니다(docs/06 Q1 이전
결정, implementation-plan 의 "비용 기록 경로" 종결).

`request_id` 가 UNIQUE 이므로 `ON CONFLICT DO NOTHING` 으로 씁니다. 재시도가 중복 행을
만들지 않습니다.

스풀은 유실 가능한 버퍼입니다. **드롭은 곧 비용 과소 집계**이므로 반드시 로그로 드러냅니다 —
조용한 유실이 비용 관제에서 가장 나쁜 실패 형태입니다.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.core.clock import utcnow
from gateway.core.context import AuthContext
from gateway.core.model import ModelPricing
from gateway.core.normalized import TokenUsage
from gateway.core.routing import BackendDecision
from gateway.schema.usage import UsageEvent

logger = structlog.get_logger(__name__)

#: usage_events.estimated_cost_usd 는 numeric(14,6) 입니다.
COST_PRECISION = Decimal("0.000001")


def calculate_cost(usage: TokenUsage, pricing: ModelPricing | None) -> Decimal:
    """전 구간 Decimal 입니다. float 를 거치면 단가의 유효숫자가 조용히 깎입니다.

    단가 행이 없으면 0 입니다. 호출은 이미 일어났으므로 기록은 남기고, 0 원으로 집계되는 것은
    카탈로그 운영 문제로 따로 드러냅니다(model.pricing_missing 경고).
    """
    if pricing is None:
        return Decimal("0")
    total = (
        Decimal(usage.input_tokens) / 1000 * pricing.input_per_1k
        + Decimal(usage.output_tokens) / 1000 * pricing.output_per_1k
        + Decimal(usage.cache_write_tokens) / 1000 * pricing.cache_write_per_1k
        + Decimal(usage.cache_read_tokens) / 1000 * pricing.cache_read_per_1k
    )
    return total.quantize(COST_PRECISION, rounding=ROUND_HALF_UP)


@dataclass
class UsageRecord:
    request_id: str
    occurred_at: datetime
    team_id: str
    user_id: str | None
    virtual_key_id: str
    model_alias: str
    provider_model_id: str
    dialect: str
    status: str
    usage: TokenUsage
    latency_ms: int
    ttft_ms: int | None
    is_streaming: bool
    estimated_cost_usd: Decimal
    pricing_id: str | None
    error_code: str | None
    client: str | None

    def to_row(self) -> dict:
        return {
            "id": uuid.uuid4(),
            "request_id": self.request_id,
            "occurred_at": self.occurred_at,
            "team_id": self.team_id,
            "user_id": self.user_id,
            "virtual_key_id": self.virtual_key_id,
            "model_alias": self.model_alias,
            "provider_model_id": self.provider_model_id,
            "dialect": self.dialect,
            "status": self.status,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cache_write_tokens": self.usage.cache_write_tokens,
            "cache_read_tokens": self.usage.cache_read_tokens,
            "estimated_usage": self.usage.estimated,
            "latency_ms": self.latency_ms,
            "ttft_ms": self.ttft_ms,
            "is_streaming": self.is_streaming,
            "estimated_cost_usd": self.estimated_cost_usd,
            "pricing_id": self.pricing_id,
            "error_code": self.error_code,
            "client": self.client,
        }


def build_record(
    *,
    request_id: str,
    auth: AuthContext,
    decision: BackendDecision,
    dialect: str,
    status: str,
    usage: TokenUsage,
    latency_ms: int,
    ttft_ms: int | None,
    is_streaming: bool,
    error_code: str | None,
    client: str | None,
) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        occurred_at=utcnow(),
        team_id=auth.team_id,
        # TEAM 소유 VK 호출은 사람에 귀속되지 않습니다.
        user_id=auth.user_id,
        virtual_key_id=auth.virtual_key_id,
        model_alias=decision.model.alias,
        provider_model_id=decision.model.provider_model_id,
        dialect=dialect,
        status=status,
        usage=usage,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        is_streaming=is_streaming,
        estimated_cost_usd=calculate_cost(usage, decision.model.pricing),
        pricing_id=decision.model.pricing_id,
        error_code=error_code,
        client=client,
    )


class UsageRecorder:
    def __init__(self, spool_max: int) -> None:
        self._spool: deque[UsageRecord] = deque(maxlen=spool_max)
        self.dropped = 0

    @property
    def spool_size(self) -> int:
        return len(self._spool)

    async def record(
        self, session_factory: async_sessionmaker[AsyncSession] | None, record: UsageRecord
    ) -> None:
        if session_factory is None:
            self._spool_record(record)
            return
        try:
            await self._insert(session_factory, [record, *self._take_spool()])
        except Exception as exc:
            logger.warning("usage.record_failed_spooled", error=str(exc))
            self._spool_record(record)

    async def drain(self, session_factory: async_sessionmaker[AsyncSession] | None) -> int:
        """DB 가 돌아왔을 때 밀린 기록을 밀어 넣습니다."""
        if session_factory is None or not self._spool:
            return 0
        pending = self._take_spool()
        try:
            await self._insert(session_factory, pending)
        except Exception as exc:
            logger.warning("usage.drain_failed", error=str(exc), count=len(pending))
            for item in pending:
                self._spool_record(item)
            return 0
        logger.info("usage.drained", count=len(pending))
        return len(pending)

    def _take_spool(self) -> list[UsageRecord]:
        pending = list(self._spool)
        self._spool.clear()
        return pending

    def _spool_record(self, record: UsageRecord) -> None:
        if len(self._spool) == self._spool.maxlen:
            # deque 가 조용히 밀어내기 전에 우리가 센다. 이 숫자가 곧 과소 집계 규모입니다.
            self.dropped += 1
            logger.error("usage.record_dropped", total_dropped=self.dropped)
        self._spool.append(record)

    async def _insert(
        self, session_factory: async_sessionmaker[AsyncSession], records: list[UsageRecord]
    ) -> None:
        if not records:
            return
        async with session_factory() as db:
            await db.execute(
                # request_id UNIQUE 로 멱등합니다. 재시도가 중복 행을 만들지 않습니다.
                insert(UsageEvent)
                .values([r.to_row() for r in records])
                .on_conflict_do_nothing(index_elements=["request_id"])
            )
            await db.commit()
