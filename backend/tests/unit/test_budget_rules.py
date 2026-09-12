"""예산 규칙 테스트 (M6).

07 문서가 "반드시 테스트로 고정할 규칙"으로 지목한 것 중 예산 몫입니다.

- 예산 **UTC 월 경계** — 특히 KST 기준 월초/월말
- 배분 **합계 초과 거절**
- 소진율·경보 단계 — 프론트가 중복 구현하지 않도록 backend 가 계산하는 값
- 설정 캐시와 집행 카운터의 **키 분리**
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core import cache_keys
from app.core.clock import month_period
from app.models.budget import BudgetConfig
from app.models.enums import BudgetPolicy, BudgetScope
from app.policy import budget as policy
from app.policy.budget import AlertLevel
from app.schemas.budgets import AllocationSetRequest, BudgetSetRequest, ReseedRequest
from app.services.budget_service import (
    SOURCE_DB,
    SOURCE_MIXED,
    SOURCE_REDIS,
    ResolvedUsage,
    UsageReader,
    _build_item,
    _combined_source,
)

KST = timezone(timedelta(hours=9))


def _d(value: str) -> Decimal:
    return Decimal(value)


# ── 기간 경계 (공유 계약) ──


@pytest.mark.parametrize(
    ("kst_moment", "expected"),
    [
        # KST 로는 10월 1일이지만 UTC 로는 아직 9월입니다. 경계를 로컬로 두면 gateway 카운터,
        # 집계 배치, 대시보드가 각자 다른 월을 봅니다.
        (datetime(2026, 10, 1, 0, 30, tzinfo=KST), "2026-09"),
        (datetime(2026, 10, 1, 8, 59, tzinfo=KST), "2026-09"),
        # KST 9시 = UTC 0시. 여기서부터 10월입니다.
        (datetime(2026, 10, 1, 9, 0, tzinfo=KST), "2026-10"),
        # 월말: KST 로는 9월 30일이지만 UTC 로도 9월입니다.
        (datetime(2026, 9, 30, 23, 59, tzinfo=KST), "2026-09"),
        # 연말 경계.
        (datetime(2027, 1, 1, 0, 30, tzinfo=KST), "2026-12"),
    ],
)
def test_month_period_is_utc_not_local(kst_moment, expected):
    assert month_period(kst_moment) == expected


def test_period_bounds_is_half_open_utc():
    start, end = policy.period_bounds("2026-09")
    assert start == datetime(2026, 9, 1, tzinfo=UTC)
    assert end == datetime(2026, 10, 1, tzinfo=UTC)
    # 끝은 포함하지 않습니다. 10월 1일 0시 이벤트는 10월 몫입니다.
    assert start <= datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC) < end


def test_period_bounds_rolls_over_year():
    assert policy.period_bounds("2026-12")[1] == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("period", ["2026-09", "2026-01", "2026-12"])
def test_valid_periods(period):
    assert policy.is_valid_period(period)


@pytest.mark.parametrize("period", ["2026-13", "2026-00", "26-09", "2026-9", "2026-09-01", ""])
def test_invalid_periods(period):
    assert not policy.is_valid_period(period)


# ── 소진율과 잔여 ──


@pytest.mark.parametrize(
    ("used", "limit", "expected"),
    [
        ("0", "100", "0.00"),
        ("81.24", "100", "81.24"),
        ("100", "100", "100.00"),
        ("150", "100", "150.00"),
        # 한도 0 은 "쓸 수 없음"입니다. 0 으로 나누지 않고, 쓴 것이 있으면 100% 입니다.
        ("0", "0", "0.00"),
        ("0.0001", "0", "100.00"),
    ],
)
def test_usage_pct(used, limit, expected):
    assert policy.usage_pct(_d(used), _d(limit)) == _d(expected)


def test_remaining_keeps_overage_negative():
    """초과분을 0 으로 깎으면 '얼마나 넘겼는가'가 화면에서 사라집니다."""
    assert policy.remaining(_d("120"), _d("100")) == _d("-20.0000")
    assert policy.remaining(_d("40"), _d("100")) == _d("60.0000")


# ── 경보 단계 ──


@pytest.mark.parametrize(
    ("used", "expected"),
    [
        ("0", AlertLevel.NORMAL),
        ("79.99", AlertLevel.NORMAL),
        ("80", AlertLevel.WARNING),
        ("89.99", AlertLevel.WARNING),
        ("90", AlertLevel.CRITICAL),
        ("99.99", AlertLevel.CRITICAL),
        ("100", AlertLevel.EXCEEDED),
        ("250", AlertLevel.EXCEEDED),
    ],
)
def test_alert_level_with_default_thresholds(used, expected):
    assert policy.alert_level(_d(used), _d("100")) == expected


def test_alert_level_uses_configured_thresholds():
    """임계값은 설정마다 다릅니다. 100 미만 중 가장 높은 것이 CRITICAL 입니다."""
    thresholds = [50, 70]
    assert policy.alert_level(_d("49"), _d("100"), thresholds) == AlertLevel.NORMAL
    assert policy.alert_level(_d("50"), _d("100"), thresholds) == AlertLevel.WARNING
    assert policy.alert_level(_d("70"), _d("100"), thresholds) == AlertLevel.CRITICAL
    assert policy.alert_level(_d("100"), _d("100"), thresholds) == AlertLevel.EXCEEDED


def test_alert_level_empty_thresholds_falls_back_to_default():
    assert policy.alert_level(_d("85"), _d("100"), []) == AlertLevel.WARNING


def test_crossed_thresholds_includes_full():
    """100 은 단계 판정에서는 EXCEEDED 에 밀리지만 **알림 목록에는 남습니다.**

    초과 시점에도 알림이 한 번은 나가야 하기 때문입니다.
    """
    assert policy.crossed_thresholds(_d("100"), _d("100"), [80, 90, 100]) == [80, 90, 100]
    assert policy.crossed_thresholds(_d("85"), _d("100"), [80, 90, 100]) == [80]
    assert policy.crossed_thresholds(_d("10"), _d("100"), [80, 90, 100]) == []


# ── 배분 ──


def test_allocation_within_limit_reports_unallocated():
    check = policy.check_allocation(_d("100"), [_d("40"), _d("35")])
    assert check.allocated_usd == _d("75.0000")
    assert check.unallocated_usd == _d("25.0000")
    assert not check.exceeds


def test_allocation_exceeding_team_limit_is_rejected():
    """하위 합이 상위를 넘을 수 있으면 팀 상한이 의미를 잃습니다(00 문서)."""
    check = policy.check_allocation(_d("100"), [_d("60"), _d("50")])
    assert check.allocated_usd == _d("110.0000")
    assert check.unallocated_usd == _d("-10.0000")
    assert check.exceeds


def test_allocation_exactly_at_limit_is_allowed():
    check = policy.check_allocation(_d("100"), [_d("60"), _d("40")])
    assert check.unallocated_usd == _d("0.0000")
    assert not check.exceeds


def test_empty_allocation_leaves_whole_limit_unallocated():
    check = policy.check_allocation(_d("100"), [])
    assert check.allocated_usd == _d("0.0000")
    assert check.unallocated_usd == _d("100.0000")


# ── 캐시 키 (공유 계약) ──


def test_budget_policy_key_shape():
    scope_id = uuid.UUID("9f2c0000-0000-0000-0000-000000000001")
    assert cache_keys.budget_policy("TEAM", scope_id) == f"policy:budget:team:{scope_id}"
    assert cache_keys.budget_policy("USER", scope_id) == f"policy:budget:user:{scope_id}"


def test_usage_counter_key_never_matches_policy_prefix():
    """설정 캐시와 소진 카운터는 **접두사가 달라야 합니다**(05 문서).

    접두사가 겹치면 설정 무효화가 카운터까지 지워 소진액이 0 으로 리셋되고, 초과 상태가
    조용히 풀립니다.
    """
    scope_id = uuid.UUID("9f2c0000-0000-0000-0000-000000000001")
    counter = cache_keys.budget_usage_counter("TEAM", scope_id, "2026-09")
    assert counter == f"budget:usage:team:{scope_id}:2026-09"
    assert not counter.startswith("policy:budget:")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100", "100.0000"),
        ("1E+2", "100.0000"),
        ("0", "0.0000"),
        ("812.43", "812.4300"),
    ],
)
def test_counter_value_never_uses_scientific_notation(value, expected):
    """gateway 의 INCRBYFLOAT 가 '1E+2' 를 파싱하지 못해 카운터가 통째로 깨집니다."""
    assert policy.counter_value(_d(value)) == expected


# ── 조회 응답 조립 ──


def _config(limit: str, thresholds: list[int] | None = None) -> BudgetConfig:
    return BudgetConfig(
        id=uuid.uuid4(),
        scope=BudgetScope.TEAM,
        scope_id=uuid.uuid4(),
        limit_usd=_d(limit),
        policy=BudgetPolicy.HARD_BLOCK,
        warn_thresholds=thresholds or [80, 90, 100],
        effective_from=datetime(2026, 9, 1, tzinfo=UTC).date(),
    )


def test_build_item_carries_source_and_derived_values():
    config = _config("1000")
    item = _build_item(config, "search-platform", ResolvedUsage(_d("812.43"), SOURCE_REDIS))

    assert item.used_usd == _d("812.43")
    assert item.remaining_usd == _d("187.5700")
    assert item.usage_pct == _d("81.24")
    assert item.alert_level == AlertLevel.WARNING
    # 운영자가 보는 숫자가 집행에 쓰이는 숫자인지 드러냅니다.
    assert item.source == SOURCE_REDIS


def test_combined_source_marks_mixed():
    """항목마다 출처가 다를 수 있습니다. 한쪽으로 뭉뚱그리면 거짓이 됩니다."""
    redis_item = _build_item(_config("100"), None, ResolvedUsage(_d("10"), SOURCE_REDIS))
    db_item = _build_item(_config("100"), None, ResolvedUsage(_d("10"), SOURCE_DB))

    assert _combined_source([redis_item, redis_item]) == SOURCE_REDIS
    assert _combined_source([db_item]) == SOURCE_DB
    assert _combined_source([redis_item, db_item]) == SOURCE_MIXED
    # 항목이 없으면 카운터를 읽은 적이 없으므로 db 입니다.
    assert _combined_source([]) == SOURCE_DB


# ── 요청 검증 ──


def test_reseed_rejects_duplicate_target():
    """같은 (scope, scope_id, period) 는 `budget_usages` 의 PK 입니다. 두 번 쓰면 충돌합니다."""
    scope_id = str(uuid.uuid4())
    item = {"scope": "TEAM", "scope_id": scope_id, "period": "2026-09", "used_usd": "10"}
    with pytest.raises(PydanticValidationError):
        ReseedRequest(items=[item, {**item, "used_usd": "20"}], reason="복구")


def test_reseed_requires_reason():
    """카운터 쓰기는 원칙의 예외이므로 사유 없이는 받지 않습니다."""
    item = {"scope": "TEAM", "scope_id": str(uuid.uuid4()), "period": "2026-09", "used_usd": "10"}
    with pytest.raises(PydanticValidationError):
        ReseedRequest(items=[item], reason="")


def test_reseed_rejects_malformed_period():
    item = {"scope": "TEAM", "scope_id": str(uuid.uuid4()), "period": "2026-9", "used_usd": "10"}
    with pytest.raises(PydanticValidationError):
        ReseedRequest(items=[item], reason="복구")


def test_allocation_rejects_duplicate_user():
    """같은 사용자가 두 번 있으면 합계 검증이 통과해도 최종 한도가 모호합니다."""
    user_id = str(uuid.uuid4())
    with pytest.raises(PydanticValidationError):
        AllocationSetRequest(
            allocations=[
                {"user_id": user_id, "limit_usd": "10"},
                {"user_id": user_id, "limit_usd": "20"},
            ]
        )


def test_budget_set_normalizes_thresholds():
    request = BudgetSetRequest(limit_usd="100", warn_thresholds=[100, 80, 80, 90])
    assert request.warn_thresholds == [80, 90, 100]


@pytest.mark.parametrize("thresholds", [[], [0], [-10], [1001]])
def test_budget_set_rejects_invalid_thresholds(thresholds):
    with pytest.raises(PydanticValidationError):
        BudgetSetRequest(limit_usd="100", warn_thresholds=thresholds)


def test_budget_set_rejects_negative_limit():
    with pytest.raises(PydanticValidationError):
        BudgetSetRequest(limit_usd="-1")


# ── 카운터 읽기 ──


class _FakeRedis:
    """mget 만 흉내 냅니다. `UsageReader.read_counters` 는 세션을 쓰지 않습니다."""

    def __init__(self, values: list[str | None] | Exception) -> None:
        self._values = values
        self.requested_keys: list[str] = []

    async def mget(self, keys: list[str]):
        self.requested_keys = keys
        if isinstance(self._values, Exception):
            raise self._values
        return self._values


async def test_read_counters_parses_present_keys_only():
    """키가 없는 것과 0 은 다릅니다. 없는 키는 결과에서 빠져 DB 폴백 대상이 됩니다."""
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    redis = _FakeRedis(["812.43", None, "0"])
    reader = UsageReader(redis, session=None)

    counters = await reader.read_counters(BudgetScope.TEAM, ids, "2026-09")

    assert counters == {ids[0]: _d("812.4300"), ids[2]: _d("0.0000")}
    assert redis.requested_keys[0] == f"budget:usage:team:{ids[0]}:2026-09"


async def test_read_counters_skips_unparsable_value():
    """손상된 값을 지우면 집행 상태가 풀립니다. 없는 것으로 보고 DB 로 떨어뜨립니다."""
    ids = [uuid.uuid4()]
    reader = UsageReader(_FakeRedis(["not-a-number"]), session=None)

    assert await reader.read_counters(BudgetScope.USER, ids, "2026-09") == {}


async def test_read_counters_survives_redis_failure():
    """Redis 장애가 조회를 실패시키지 않습니다. DB 로 떨어지고 source 가 그것을 드러냅니다."""
    reader = UsageReader(_FakeRedis(ConnectionError("redis down")), session=None)

    assert await reader.read_counters(BudgetScope.TEAM, [uuid.uuid4()], "2026-09") == {}
