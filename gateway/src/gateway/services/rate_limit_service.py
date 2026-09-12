"""rate limit 집행.

두 축(주체 / 전역)을 해석하고 카운터를 다룹니다. 해석 규칙은 `policy/rate_limits` 에 순수
함수로 있고, 여기에는 **I/O 와 되돌리기 규칙**만 둡니다.

되돌리기 규칙이 한도 종류마다 다릅니다. 같아 보이지만 재는 대상이 달라서입니다(docs/08).

    rpm          증가 후 비교. 거절해도 **되돌리지 않습니다** — 거절된 요청도 도달한 요청이고,
                 차단 중에 계속 두드리면 계속 차단되는 것이 의도된 백프레셔입니다.
    tpm          두 축을 **먼저 다 확인한 뒤** 차감합니다. 증가 후 비교로 하면 거절된 큰 요청
                 하나의 추정치가 그 분 전체를 막습니다.
    concurrency  거절 시 **되돌립니다.** 속도가 아니라 현재 점유 수를 재는 게이지라,
                 되돌리지 않으면 단조 증가해 한도가 영구히 막힙니다.

모든 연산이 정확히 한 키만 건드립니다. 그래서 ElastiCache cluster mode 용 해시 태그가
필요 없습니다 — 같은 슬롯을 요구하는 것은 multi-key 연산뿐입니다.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.config import Settings
from gateway.core import cache, cache_keys
from gateway.core.clock import epoch_minute
from gateway.core.context import AuthContext
from gateway.core.errors import AuthOutcome, ErrorCode, GatewayError
from gateway.core.normalized import (
    NormalizedRequest,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from gateway.policy.rate_limits import (
    ALL_MODELS,
    RPM,
    TPM,
    EffectiveLimits,
    Limit,
    LimitConfig,
    resolve,
)
from gateway.schema.model import RateLimitConfig

logger = structlog.get_logger(__name__)

SUBJECT_SCOPES = ("VIRTUAL_KEY", "USER", "TEAM")


@dataclass
class Reservation:
    """집행이 잡아 둔 자원. `Finalize` 가 정산·반납합니다.

    반납은 **멱등**해야 합니다. 두 번 반납하면 게이지가 음수로 새고, 그 뒤로 동시성 한도가
    사실상 사라집니다.
    """

    #: (키, 선차감한 추정 토큰). 정산은 차감한 그 윈도 키에 되돌려야 합니다.
    tpm: list[tuple[str, int]] = field(default_factory=list)
    concurrency: list[str] = field(default_factory=list)
    finalized: bool = False

    @property
    def empty(self) -> bool:
        return not self.tpm and not self.concurrency


class RateLimitService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ── 집행 ──

    async def charge(
        self,
        *,
        auth: AuthContext,
        request: NormalizedRequest,
        model_alias: str,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> Reservation:
        """통과하면 `Reservation`, 걸리면 `GatewayError(429)`.

        Redis 가 없으면 셀 수 없으므로 **통과시킵니다**(fail-open). upstream 용량은 Bedrock
        자체 쿼터가 2차로 막고 있어, 보호막 한 겹이 잠시 없어도 벌거벗지 않습니다(docs/08).
        """
        if redis is None:
            logger.warning("ratelimit.redis_unavailable_fail_open")
            return Reservation()

        subject, global_ = await self.resolve(
            auth=auth, model_alias=model_alias, redis=redis, session_factory=session_factory
        )
        if subject.empty and global_.empty:
            return Reservation()

        minute = epoch_minute()
        reservation = Reservation()
        try:
            await self._charge_rpm([subject.rpm, global_.rpm], redis, minute)
            await self._charge_tpm(
                [subject.tpm, global_.tpm], redis, minute, request, reservation
            )
            await self._charge_concurrency(
                [subject.concurrency, global_.concurrency], redis, reservation
            )
        except GatewayError:
            # 이미 잡은 동시성 슬롯을 놓고 거절하면 게이지가 샙니다.
            await self.finalize(redis, reservation, actual_tokens=None)
            raise
        return reservation

    async def _charge_rpm(self, limits: Sequence[Limit | None], redis, minute: int) -> None:
        for limit in [x for x in limits if x is not None]:
            key = self._key(limit, f"{RPM}:{minute}")
            try:
                count = await redis.incr(key)
                await redis.expire(key, self._settings.rate_limit_window_ttl_seconds, nx=True)
            except Exception as exc:
                logger.warning("ratelimit.rpm_failed_fail_open", key=key, error=str(exc))
                continue
            if count > limit.value:
                raise self._rejected(limit, observed=count, minute=minute)

    async def _charge_tpm(
        self,
        limits: Sequence[Limit | None],
        redis,
        minute: int,
        request: NormalizedRequest,
        reservation: Reservation,
    ) -> None:
        applicable = [x for x in limits if x is not None]
        if not applicable:
            return
        estimate = self.estimate_tokens(request)

        # 두 축을 **먼저 다 확인**합니다. 축 하나를 차감한 뒤 다른 축에서 걸리면 남는 차감을
        # 되돌려야 하고, 되돌리기는 실패할 수 있는 또 하나의 지점입니다.
        checked: list[tuple[Limit, str]] = []
        for limit in applicable:
            key = self._key(limit, f"{TPM}:{minute}")
            try:
                raw = await redis.get(key)
            except Exception as exc:
                logger.warning("ratelimit.tpm_failed_fail_open", key=key, error=str(exc))
                continue
            used = int(raw) if raw is not None else 0
            if used + estimate > limit.value:
                raise self._rejected(limit, observed=used + estimate, minute=minute)
            checked.append((limit, key))

        for _limit, key in checked:
            try:
                await redis.incrby(key, estimate)
                await redis.expire(key, self._settings.rate_limit_window_ttl_seconds, nx=True)
            except Exception as exc:
                logger.warning("ratelimit.tpm_charge_failed", key=key, error=str(exc))
                continue
            reservation.tpm.append((key, estimate))

    async def _charge_concurrency(
        self, limits: Sequence[Limit | None], redis, reservation: Reservation
    ) -> None:
        for limit in [x for x in limits if x is not None]:
            key = self._key(limit, "conc")
            try:
                count = await redis.incr(key)
                # TTL 이 누수 방어입니다. pod 가 스트림 도중 죽으면 반납이 실행되지 않아
                # 슬롯이 영원히 남습니다. NX 라 진행 중인 요청이 만료를 밀어내지 않습니다 —
                # 밀어내면 바쁜 키일수록 누수가 오래갑니다.
                await redis.expire(key, self._settings.concurrency_lease_ttl_seconds, nx=True)
            except Exception as exc:
                logger.warning("ratelimit.concurrency_failed_fail_open", key=key, error=str(exc))
                continue
            reservation.concurrency.append(key)
            if count > limit.value:
                raise self._rejected(limit, observed=count, minute=None)

    # ── 정산·반납 ──

    async def finalize(
        self, redis, reservation: Reservation, *, actual_tokens: int | None
    ) -> None:
        """tpm 을 실제값으로 정산하고 동시성 슬롯을 반납합니다.

        `actual_tokens` 가 None 이면 정산 없이 선차감을 그대로 되돌립니다 — 거절돼서 호출이
        일어나지 않았다는 뜻입니다.
        """
        if reservation.finalized or redis is None or reservation.empty:
            reservation.finalized = True
            return
        reservation.finalized = True

        for key, estimate in reservation.tpm:
            delta = (actual_tokens - estimate) if actual_tokens is not None else -estimate
            if delta == 0:
                continue
            try:
                await redis.incrby(key, delta)
            except Exception as exc:
                logger.warning("ratelimit.tpm_settle_failed", key=key, error=str(exc))

        for key in reservation.concurrency:
            try:
                await redis.decr(key)
            except Exception as exc:
                # 반납 실패는 TTL 이 치웁니다. 그때까지 그 슬롯만큼 용량이 줄어듭니다.
                logger.warning("ratelimit.concurrency_release_failed", key=key, error=str(exc))

    # ── 해석 ──

    async def resolve(
        self,
        *,
        auth: AuthContext,
        model_alias: str,
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> tuple[EffectiveLimits, EffectiveLimits]:
        """(주체 축, 전역 축). 후보는 가장 구체적인 것부터 정렬해 넘깁니다."""
        subject_targets: list[tuple[str, str | None]] = [
            ("VIRTUAL_KEY", auth.virtual_key_id),
            ("USER", auth.user_id),  # TEAM 소유 VK 는 None 이라 건너뜁니다.
            ("TEAM", auth.team_id),
        ]

        wanted: list[tuple[str, str | None, str | None]] = []
        for scope, scope_id in subject_targets:
            if scope_id is None:
                continue
            wanted.append((scope, scope_id, model_alias))
            wanted.append((scope, scope_id, None))
        wanted.append(("GLOBAL", None, model_alias))
        wanted.append(("GLOBAL", None, None))

        found = await self._load(wanted, redis, session_factory)
        subject = resolve(found[k] for k in wanted if k[0] in SUBJECT_SCOPES)
        global_ = resolve(found[k] for k in wanted if k[0] == "GLOBAL")
        return subject, global_

    async def _load(
        self,
        wanted: Sequence[tuple[str, str | None, str | None]],
        redis,
        session_factory: async_sessionmaker[AsyncSession] | None,
    ) -> dict[tuple[str, str | None, str | None], LimitConfig | None]:
        """캐시 우선, miss 는 **한 번의 쿼리**로 모아 읽습니다.

        후보가 최대 8개라 miss 마다 쿼리를 날리면 요청 하나가 DB 왕복 8번이 됩니다.
        """
        found: dict[tuple[str, str | None, str | None], LimitConfig | None] = {}
        missing: list[tuple[str, str | None, str | None]] = []

        for key in wanted:
            cached = await cache.get_json(redis, cache_keys.rate_limit_policy(*key))
            if cached is None:
                missing.append(key)
            elif cached.get("set"):
                found[key] = LimitConfig.from_dict(cached["config"])
            else:
                found[key] = None

        if not missing:
            return found
        if session_factory is None:
            # 설정을 확인할 수 없으면 집행하지 않습니다(fail-open). 확인 못 한 한도로
            # 거절하면 정상 트래픽이 의존성 장애에 함께 넘어집니다.
            for key in missing:
                found[key] = None
            return found

        try:
            rows = await self._query(missing, session_factory)
        except Exception as exc:
            logger.warning("ratelimit.config_lookup_failed_fail_open", error=str(exc))
            for key in missing:
                found[key] = None
            return found

        for key in missing:
            config = rows.get(key)
            found[key] = config
            # **미설정도 캐시합니다.** 한도가 적은 환경에서 음성 캐시가 없는 정책 캐시는
            # 캐시가 아닙니다 — 거의 모든 요청이 DB 를 봅니다.
            payload = {"set": True, "config": config.to_dict()} if config else {"set": False}
            await cache.set_json(
                redis,
                cache_keys.rate_limit_policy(*key),
                payload,
                self._settings.policy_cache_ttl_seconds,
            )
        return found

    async def _query(
        self,
        missing: Sequence[tuple[str, str | None, str | None]],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> dict[tuple[str, str | None, str | None], LimitConfig]:
        scopes = {k[0] for k in missing}
        ids = {uuid.UUID(k[1]) for k in missing if k[1] is not None}
        aliases = {k[2] for k in missing if k[2] is not None}

        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(RateLimitConfig).where(
                        RateLimitConfig.is_active.is_(True),
                        RateLimitConfig.scope.in_(scopes),
                        or_(
                            RateLimitConfig.scope_id.is_(None),
                            RateLimitConfig.scope_id.in_(ids) if ids else False,
                        ),
                        or_(
                            RateLimitConfig.model_alias.is_(None),
                            RateLimitConfig.model_alias.in_(aliases) if aliases else False,
                        ),
                    )
                )
            ).scalars().all()

        return {
            (
                str(row.scope),
                str(row.scope_id) if row.scope_id else None,
                row.model_alias,
            ): LimitConfig(
                scope=str(row.scope),
                scope_id=str(row.scope_id) if row.scope_id else None,
                model_alias=row.model_alias,
                rpm_limit=row.rpm_limit,
                tpm_limit=row.tpm_limit,
                concurrency_limit=row.concurrency_limit,
            )
            for row in rows
        }

    # ── 도구 ──

    def estimate_tokens(self, request: NormalizedRequest) -> int:
        """선차감용 추정치 = 입력 추정 + `max_tokens`.

        정확한 토크나이저를 요청 경로에 두지 않습니다. 모델마다 다른 토크나이저를 gateway 가
        들고 있어야 하고 그 비용이 매 요청에 붙습니다. **추정은 정산으로 교정되므로 윈도
        안에서만 부정확하고 누적되지 않습니다**(docs/08).

        이미지는 세지 않습니다 — base64 길이는 토큰 수와 비례하지 않아, 세면 오히려
        추정이 더 틀립니다.
        """
        chars = 0
        for block in request.system or []:
            chars += _block_chars(block)
        for message in request.messages:
            for block in message.content:
                chars += _block_chars(block)
        for tool in request.tools:
            chars += len(tool.name) + len(tool.description or "") + len(str(tool.input_schema))

        per_token = max(self._settings.tpm_chars_per_token, 1)
        return math.ceil(chars / per_token) + request.max_tokens

    def _key(self, limit: Limit, window: str) -> str:
        return cache_keys.rate_limit_counter(
            limit.scope, limit.scope_id, limit.model_alias or ALL_MODELS, window
        )

    def _rejected(self, limit: Limit, *, observed: int, minute: int | None) -> GatewayError:
        """어느 층에서 걸렸는지는 **로그에만** 남깁니다.

        `auth_events` 에 층을 담을 컬럼이 없고, 그 하나를 위해 스키마 변경을 요청할 만큼
        조회 요구가 분명하지 않습니다(docs/08).
        """
        logger.info(
            "ratelimit.blocked",
            limit_type=limit.limit_type,
            scope=limit.scope,
            scope_id=limit.scope_id,
            model_alias=limit.model_alias,
            limit=limit.value,
            observed=observed,
        )
        return GatewayError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            f"{limit.limit_type} limit of {limit.value} exceeded for {limit.scope.lower()}",
            retry_after=_retry_after(minute),
            outcome=AuthOutcome.RATE_LIMITED,
        )


def _block_chars(block) -> int:
    if isinstance(block, TextBlock):
        return len(block.text)
    if isinstance(block, ThinkingBlock):
        return len(block.thinking)
    if isinstance(block, ToolUseBlock):
        return len(block.name) + len(str(block.input))
    if isinstance(block, ToolResultBlock):
        return len(str(block.content))
    return 0  # ImageBlock


def _retry_after(minute: int | None) -> int:
    """윈도가 닫힐 때까지의 초.

    동시성(`minute is None`)은 윈도가 없습니다. 앞선 요청이 끝나야 풀리므로 짧은 고정값을
    주고, 그 값이 곧 client 의 재시도 간격이 됩니다.
    """
    if minute is None:
        return 1
    remaining = (minute + 1) * 60 - time.time()
    return max(1, math.ceil(remaining))
