"""rate limit 설정의 DB 의존 동작 (M8).

단위 테스트가 해석 규칙을 고정하고, 여기서는 **DB 없이는 검증할 수 없는 것**을 봅니다 —
부분 unique index, 계층 제약의 동시성, 캐시 팬아웃 대상 키.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import cache_keys
from app.core.exceptions import ConflictError, ForbiddenError
from app.models.enums import ApiDialect, ModelStatus, Provider, RateLimitScope, UserRole
from app.models.model import ModelAlias, ModelPricing, RateLimitConfig
from app.schemas.rate_limits import RateLimitSetRequest
from app.services.rate_limit_service import RateLimitService
from tests.integration.conftest import admin_actor, seed_team, seed_user, seed_virtual_key

ALIAS = "claude-sonnet-4"


async def seed_model(session, created_by, alias: str = ALIAS) -> str:
    """카탈로그의 ACTIVE alias. 캐시 팬아웃 대상 목록의 원천입니다."""
    session.add(
        ModelAlias(
            alias=alias,
            display_name=alias,
            provider=Provider.BEDROCK,
            provider_model_id=f"apac.anthropic.{alias}-v1:0",
            supported_dialects=[ApiDialect.OPENAI_CHAT],
            status=ModelStatus.ACTIVE,
            created_by=created_by,
        )
    )
    session.add(
        ModelPricing(
            id=uuid.uuid4(),
            model_alias=alias,
            input_price_per_1k=Decimal("0.003"),
            output_price_per_1k=Decimal("0.015"),
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            created_by=created_by,
        )
    )
    await session.commit()
    return alias


def leader_actor(user_id, team_id):
    from app.core.auth import CurrentAdmin

    return CurrentAdmin(
        user_id=user_id, email="leader@example.com", role=UserRole.TEAM_LEADER, team_id=team_id
    )


async def _fixtures(session):
    team_id = await seed_team(session)
    admin_id = await seed_user(session, team_id, display_name="admin")
    member_id = await seed_user(session, team_id, display_name="member")
    await seed_model(session, admin_id)
    return team_id, admin_id, member_id, admin_actor(admin_id, team_id)


# ── 부분 unique index ──


async def test_upsert_keeps_single_active_row(db_session, cache_mgr, ctx):
    """같은 `(scope, scope_id, model_alias)` 활성 행은 하나뿐입니다 — DB 제약입니다."""
    team_id, _, _, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=900, tpm_limit=400000),
        actor=actor,
        ctx=ctx,
    )

    rows = (
        await db_session.execute(
            select(RateLimitConfig).where(
                RateLimitConfig.scope == RateLimitScope.TEAM,
                RateLimitConfig.scope_id == team_id,
                RateLimitConfig.is_active.is_(True),
            )
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].rpm_limit == 900
    assert rows[0].tpm_limit == 400000


async def test_model_dimension_is_a_separate_row(db_session, cache_mgr, ctx):
    """전체 모델 설정과 특정 모델 설정은 **다른 행**입니다. 둘 다 후보로 남습니다."""
    team_id, _, _, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)

    for alias, rpm in ((None, 600), (ALIAS, 100)):
        await service.set_limit(
            db_session,
            scope=RateLimitScope.TEAM,
            scope_id=team_id,
            model_alias=alias,
            data=RateLimitSetRequest(rpm_limit=rpm),
            actor=actor,
            ctx=ctx,
        )

    rows = (
        await db_session.execute(
            select(RateLimitConfig).where(RateLimitConfig.is_active.is_(True))
        )
    ).scalars().all()
    assert len(rows) == 2


async def test_delete_removes_layer_entirely(db_session, cache_mgr, ctx):
    """`DELETE` 는 `null` 저장과 다릅니다 — 이 층이 없어지고 상위로 폴백합니다."""
    team_id, _, member_id, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=100),
        actor=actor,
        ctx=ctx,
    )

    before = await service.effective(
        db_session, user_id=member_id, virtual_key_id=None, model_alias=None, actor=actor
    )
    assert before.effective_limits["rpm_limit"].value == 100

    await service.delete_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        actor=actor,
        ctx=ctx,
    )

    after = await service.effective(
        db_session, user_id=member_id, virtual_key_id=None, model_alias=None, actor=actor
    )
    assert after.effective_limits["rpm_limit"].value == 600
    assert after.effective_limits["rpm_limit"].resolved_from == "TEAM"


# ── 계층 제약 ──


async def test_leader_cannot_exceed_team_limit(db_session, cache_mgr, ctx):
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)
    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )

    leader = leader_actor(admin_id, team_id)
    with pytest.raises(ConflictError) as exc:
        await service.set_limit(
            db_session,
            scope=RateLimitScope.USER,
            scope_id=member_id,
            model_alias=None,
            data=RateLimitSetRequest(rpm_limit=1000),
            actor=leader,
            ctx=ctx,
        )
    assert exc.value.code == "limit_exceeds_parent"
    assert exc.value.details["violations"][0]["parent_value"] == 600


async def test_admin_may_exceed_parent_but_it_is_recorded(db_session, cache_mgr, ctx):
    """ADMIN 은 제약을 받지 않지만 **감사에 남고** 응답에 배지가 붙습니다(06 문서)."""
    from app.models.audit import AuditLog

    team_id, _, member_id, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)
    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )

    result = await service.set_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=1000),
        actor=actor,
        ctx=ctx,
    )
    assert result.config.exceeds_parent is True

    logs = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "SET_USER_RATE_LIMIT")
        )
    ).scalars().all()
    assert logs[-1].changes["exceeds_parent"] == ["rpm_limit"]


async def test_lowering_team_limit_warns_instead_of_rejecting(db_session, cache_mgr, ctx):
    """연쇄 자동 조정은 관리자가 의도하지 않은 값 변경을 만듭니다. 목록으로 알립니다."""
    team_id, _, member_id, actor = await _fixtures(db_session)
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=500),
        actor=actor,
        ctx=ctx,
    )

    result = await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=100),
        actor=actor,
        ctx=ctx,
    )

    assert result.config.rpm_limit == 100  # 거절하지 않았습니다
    assert len(result.conflicting_children) == 1
    assert result.conflicting_children[0].scope_id == str(member_id)
    assert result.conflicting_children[0].exceeds["rpm_limit"] == {"child": 500, "parent": 100}


async def test_concurrent_upsert_of_same_target_does_not_collide(
    db_session, session_factory, cache_mgr, ctx
):
    """같은 조합에 대한 동시 upsert 가 부분 unique index 에서 터지지 않아야 합니다.

    행이 없을 때 `SELECT ... FOR UPDATE` 는 잠글 대상이 없어, 두 요청이 동시에 INSERT 하면
    하나가 IntegrityError 로 500 이 됩니다. 대상 단위 advisory lock 이 뒤의 요청을 UPDATE
    경로로 보냅니다.

    rate limit 에는 예산 같은 **합계 불변식이 없습니다** — 규칙은 "각 하위 ≤ 상위"이고
    하위끼리 더해지지 않습니다. 그래서 여기서 막는 것은 write skew 가 아니라 쓰기 충돌입니다.
    """
    team_id, admin_id, member_id, actor = await _fixtures(db_session)

    async def put(rpm):
        async with session_factory() as session:
            return await RateLimitService(cache_mgr).set_limit(
                session,
                scope=RateLimitScope.USER,
                scope_id=member_id,
                model_alias=None,
                data=RateLimitSetRequest(rpm_limit=rpm),
                actor=admin_actor(admin_id, team_id),
                ctx=ctx,
            )

    results = await asyncio.gather(put(100), put(200), return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"동시 upsert 가 충돌했습니다: {failures}"

    rows = (
        await db_session.execute(
            select(RateLimitConfig).where(
                RateLimitConfig.scope == RateLimitScope.USER,
                RateLimitConfig.scope_id == member_id,
                RateLimitConfig.is_active.is_(True),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].rpm_limit in (100, 200)  # 나중 것이 이깁니다


async def test_each_child_is_compared_to_parent_not_their_sum(db_session, cache_mgr, ctx):
    """rate limit 은 **속도**라 하위끼리 더해지지 않습니다.

    600 rpm 팀에 400 rpm 멤버가 둘 있어도 위반이 아닙니다 — 팀 한도는 gateway 가 따로
    집행합니다. 예산(월 총량)과 규칙이 다른 지점이라 명시적으로 고정합니다.
    """
    team_id, admin_id, member_a, actor = await _fixtures(db_session)
    member_b = await seed_user(db_session, team_id, display_name="b")
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )

    leader = leader_actor(admin_id, team_id)
    for member in (member_a, member_b):
        result = await service.set_limit(
            db_session,
            scope=RateLimitScope.USER,
            scope_id=member,
            model_alias=None,
            data=RateLimitSetRequest(rpm_limit=400),
            actor=leader,
            ctx=ctx,
        )
        assert result.config.rpm_limit == 400
        assert result.config.exceeds_parent is False


# ── 인가 ──


async def test_leader_cannot_set_team_limit(db_session, cache_mgr, ctx):
    """팀 한도 자체는 ADMIN 만 바꿉니다. 팀장은 그 안에서 배분만 합니다(06 문서)."""
    team_id, admin_id, _, _ = await _fixtures(db_session)
    leader = leader_actor(admin_id, team_id)

    with pytest.raises(ForbiddenError):
        await RateLimitService(cache_mgr).set_limit(
            db_session,
            scope=RateLimitScope.TEAM,
            scope_id=team_id,
            model_alias=None,
            data=RateLimitSetRequest(rpm_limit=600),
            actor=leader,
            ctx=ctx,
        )


async def test_leader_cannot_touch_other_team_member(db_session, cache_mgr, ctx):
    team_id, admin_id, _, _ = await _fixtures(db_session)
    other_team = await seed_team(db_session, name="other-team")
    outsider = await seed_user(db_session, other_team, display_name="outsider")

    with pytest.raises(ForbiddenError):
        await RateLimitService(cache_mgr).set_limit(
            db_session,
            scope=RateLimitScope.USER,
            scope_id=outsider,
            model_alias=None,
            data=RateLimitSetRequest(rpm_limit=10),
            actor=leader_actor(admin_id, team_id),
            ctx=ctx,
        )


# ── 캐시 무효화 팬아웃 ──


async def test_all_model_setting_invalidates_every_active_alias(
    db_session, cache_mgr, redis_client, ctx
):
    """`model_alias=NULL` 설정은 모든 모델에 영향을 줍니다.

    gateway 는 요청의 alias 로 키를 만들어 읽으므로 그 alias 각각의 키가 낡습니다.
    `SCAN` 패턴 대신 **카탈로그에서 ACTIVE 목록을 읽어 정확히** 지웁니다(06 문서).
    """
    team_id, admin_id, _, actor = await _fixtures(db_session)
    await seed_model(db_session, admin_id, "claude-haiku-4")

    # gateway 가 채워 둔 상태를 흉내 냅니다.
    keys = [
        cache_keys.rate_limit_policy("TEAM", team_id, None),
        cache_keys.rate_limit_policy("TEAM", team_id, ALIAS),
        cache_keys.rate_limit_policy("TEAM", team_id, "claude-haiku-4"),
    ]
    counter = cache_keys.rate_limit_counter("TEAM", team_id, ALIAS, "60s")
    for key in keys:
        await redis_client.set(key, "cached")
    await redis_client.set(counter, "42")

    await RateLimitService(cache_mgr).set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )

    assert [await redis_client.get(key) for key in keys] == [None, None, None]
    # 카운터는 **절대** 지우지 않습니다. 지우면 진행 중인 윈도가 리셋돼 한도가 뚫립니다.
    assert await redis_client.get(counter) == "42"


async def test_model_setting_invalidates_only_that_alias(
    db_session, cache_mgr, redis_client, ctx
):
    team_id, admin_id, _, actor = await _fixtures(db_session)
    await seed_model(db_session, admin_id, "claude-haiku-4")

    target = cache_keys.rate_limit_policy("TEAM", team_id, ALIAS)
    untouched = cache_keys.rate_limit_policy("TEAM", team_id, "claude-haiku-4")
    await redis_client.set(target, "cached")
    await redis_client.set(untouched, "cached")

    await RateLimitService(cache_mgr).set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=ALIAS,
        data=RateLimitSetRequest(rpm_limit=100),
        actor=actor,
        ctx=ctx,
    )

    assert await redis_client.get(target) is None
    assert await redis_client.get(untouched) == "cached"


# ── 해석 (실제 데이터) ──


async def test_effective_resolves_two_axes_from_db(db_session, cache_mgr, ctx):
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    vk_id = await seed_virtual_key(
        db_session, team_id=team_id, owner_id=member_id, created_by=admin_id
    )
    service = RateLimitService(cache_mgr)

    async def put(scope, scope_id, alias, **limits):
        await service.set_limit(
            db_session,
            scope=scope,
            scope_id=scope_id,
            model_alias=alias,
            data=RateLimitSetRequest(**limits),
            actor=actor,
            ctx=ctx,
        )

    await put(RateLimitScope.TEAM, team_id, None, rpm_limit=600, tpm_limit=400000)
    await put(RateLimitScope.USER, member_id, None, rpm_limit=100)
    await put(RateLimitScope.GLOBAL, None, ALIAS, rpm_limit=2000)

    result = await service.effective(
        db_session, user_id=member_id, virtual_key_id=vk_id, model_alias=ALIAS, actor=actor
    )

    # 주체 축: rpm 은 USER, tpm 은 TEAM — 한도 종류별 독립 폴백
    assert result.effective_limits["rpm_limit"].value == 100
    assert result.effective_limits["rpm_limit"].resolved_from == "USER"
    assert result.effective_limits["tpm_limit"].value == 400000
    assert result.effective_limits["tpm_limit"].resolved_from == "TEAM"
    assert result.effective_limits["concurrency_limit"].value is None

    # 전역 축은 따로. 주체 한도가 덮지 않습니다.
    assert result.global_limits["rpm_limit"].value == 2000
    assert result.global_limits["rpm_limit"].resolved_from == "GLOBAL:model"


async def test_tree_shows_inheritance_and_badge(db_session, cache_mgr, ctx):
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    inheritor = await seed_user(db_session, team_id, display_name="inheritor")
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=1000),
        actor=actor,
        ctx=ctx,
    )

    tree = await service.tree(db_session, team_id=team_id, model_alias=None, actor=actor)
    by_user = {member.user_id: member for member in tree.members}

    # 직접 설정이 있는 멤버는 상위 초과 배지가 붙습니다.
    assert by_user[str(member_id)].own.exceeds_parent is True
    assert by_user[str(member_id)].effective_limits["rpm_limit"].value == 1000
    # 설정이 없는 멤버는 팀 값을 상속합니다.
    assert by_user[str(inheritor)].own is None
    assert by_user[str(inheritor)].effective_limits["rpm_limit"].value == 600
    assert by_user[str(inheritor)].effective_limits["rpm_limit"].resolved_from == "TEAM"


async def test_usage_reports_unavailable_without_breaking(db_session, cache_mgr, ctx):
    """관측이 안 된다고 관리 기능이 멈추면 안 됩니다(06 문서).

    카운터 키 규약이 Phase 4 미확정이라 지금은 항상 불가용입니다. 그래도 200 입니다.
    """
    team_id, _, _, actor = await _fixtures(db_session)
    result = await RateLimitService(cache_mgr).usage(
        db_session, scope=RateLimitScope.TEAM, scope_id=team_id, model_alias=None, actor=actor
    )
    assert result.available is False
    assert result.reason
    assert result.entries == []


# ── 리뷰 회귀 (M8 review) ──


async def test_tree_without_alias_ignores_model_scoped_configs(db_session, cache_mgr, ctx):
    """모델 미지정 조회에 모델 전용 설정이 섞이면 안 됩니다(리뷰 P1).

    `claude-x` 전용 50 이 팀 전체 600 을 덮으면, 화면이 "이 팀의 기본 한도는 50" 이라고
    잘못 말하고 상위 초과 판단도 그 잘못된 기준으로 이뤄집니다.
    """
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    await seed_model(db_session, admin_id, "claude-x")
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias="claude-x",
        data=RateLimitSetRequest(rpm_limit=50),
        actor=actor,
        ctx=ctx,
    )

    tree = await service.tree(db_session, team_id=team_id, model_alias=None, actor=actor)

    assert tree.team_limits.rpm_limit == 600
    assert tree.team_limits.model_alias is None
    by_user = {m.user_id: m for m in tree.members}
    assert by_user[str(member_id)].effective_limits["rpm_limit"].value == 600
    assert by_user[str(member_id)].effective_limits["rpm_limit"].resolved_from == "TEAM"


async def test_tree_with_alias_prefers_that_model(db_session, cache_mgr, ctx):
    """반대로 모델을 지정하면 그 모델 설정이 전체 설정을 이깁니다."""
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    await seed_model(db_session, admin_id, "claude-x")
    service = RateLimitService(cache_mgr)

    for alias, rpm in ((None, 600), ("claude-x", 50)):
        await service.set_limit(
            db_session,
            scope=RateLimitScope.TEAM,
            scope_id=team_id,
            model_alias=alias,
            data=RateLimitSetRequest(rpm_limit=rpm),
            actor=actor,
            ctx=ctx,
        )

    tree = await service.tree(db_session, team_id=team_id, model_alias="claude-x", actor=actor)

    assert tree.team_limits.rpm_limit == 50
    by_user = {m.user_id: m for m in tree.members}
    assert by_user[str(member_id)].effective_limits["rpm_limit"].value == 50
    assert by_user[str(member_id)].effective_limits["rpm_limit"].resolved_from == "TEAM:model"


async def test_tree_badge_uses_same_model_dimension(db_session, cache_mgr, ctx):
    """상위 초과 배지도 같은 차원으로 판단해야 합니다.

    다른 모델의 낮은 팀 한도를 기준으로 삼으면 정상 설정에 초과 배지가 붙습니다.
    """
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    await seed_model(db_session, admin_id, "claude-x")
    service = RateLimitService(cache_mgr)

    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=600),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.TEAM,
        scope_id=team_id,
        model_alias="claude-x",
        data=RateLimitSetRequest(rpm_limit=50),
        actor=actor,
        ctx=ctx,
    )
    await service.set_limit(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        data=RateLimitSetRequest(rpm_limit=500),
        actor=actor,
        ctx=ctx,
    )

    tree = await service.tree(db_session, team_id=team_id, model_alias=None, actor=actor)
    member = next(m for m in tree.members if m.user_id == str(member_id))

    # 500 ≤ 600 이므로 초과가 아닙니다. claude-x 의 50 을 기준으로 삼으면 초과로 잘못 뜹니다.
    assert member.own.rpm_limit == 500
    assert member.own.exceeds_parent is False


async def test_effective_rejects_mismatched_user_and_key(db_session, cache_mgr, ctx):
    """키의 실제 소유자와 다른 `user_id` 조합은 거절합니다(리뷰 P1).

    존재하지 않는 (사용자, 키) 조합의 정책 계층을 계산하면 화면이 실제와 다른 한도를
    보여줍니다.
    """
    from app.core.exceptions import ValidationError

    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    other_member = await seed_user(db_session, team_id, display_name="other")
    key_id = await seed_virtual_key(
        db_session, team_id=team_id, owner_id=member_id, created_by=admin_id
    )

    with pytest.raises(ValidationError) as exc:
        await RateLimitService(cache_mgr).effective(
            db_session,
            user_id=other_member,
            virtual_key_id=key_id,
            model_alias=None,
            actor=actor,
        )
    assert exc.value.code == "subject_mismatch"


async def test_member_cannot_read_another_members_key_policy(db_session, cache_mgr, ctx):
    """자기 user_id + 남의 key_id 조합으로 소유권 검사를 통과할 수 없어야 합니다(리뷰 P1)."""
    from app.core.auth import CurrentAdmin

    team_id, admin_id, owner_id, _ = await _fixtures(db_session)
    intruder_id = await seed_user(db_session, team_id, display_name="intruder")
    key_id = await seed_virtual_key(
        db_session, team_id=team_id, owner_id=owner_id, created_by=admin_id
    )

    intruder = CurrentAdmin(
        user_id=intruder_id,
        email="intruder@example.com",
        role=UserRole.MEMBER,
        team_id=team_id,
    )

    # 자기 id 를 함께 보내도 통과하지 못합니다. 조합이 실제와 다르므로 인가 판정 **이전에**
    # 거절됩니다 — 소유권은 호출자가 준 id 가 아니라 키가 말하는 소유자로 판정합니다.
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        await RateLimitService(cache_mgr).effective(
            db_session,
            user_id=intruder_id,
            virtual_key_id=key_id,
            model_alias=None,
            actor=intruder,
        )
    assert exc.value.code == "subject_mismatch"

    # user_id 를 빼도 마찬가지입니다.
    with pytest.raises(ForbiddenError):
        await RateLimitService(cache_mgr).effective(
            db_session, user_id=None, virtual_key_id=key_id, model_alias=None, actor=intruder
        )


async def test_key_owner_can_read_own_key_policy(db_session, cache_mgr, ctx):
    """소유자 본인은 볼 수 있습니다 — 막는 것은 조합 위조이지 본인 조회가 아닙니다."""
    from app.core.auth import CurrentAdmin

    team_id, admin_id, owner_id, _ = await _fixtures(db_session)
    key_id = await seed_virtual_key(
        db_session, team_id=team_id, owner_id=owner_id, created_by=admin_id
    )
    owner = CurrentAdmin(
        user_id=owner_id, email="owner@example.com", role=UserRole.MEMBER, team_id=team_id
    )

    result = await RateLimitService(cache_mgr).effective(
        db_session, user_id=None, virtual_key_id=key_id, model_alias=None, actor=owner
    )
    assert result.subject["virtual_key_id"] == str(key_id)
    assert result.subject["user_id"] == str(owner_id)


async def test_leader_list_applies_requested_scope_id(db_session, cache_mgr, ctx):
    """팀장이 준 `scope_id` 가 무시되면 권한 범위 전체가 돌아옵니다(리뷰 P2)."""
    team_id, admin_id, member_id, actor = await _fixtures(db_session)
    other_member = await seed_user(db_session, team_id, display_name="other")
    service = RateLimitService(cache_mgr)

    for target in (member_id, other_member):
        await service.set_limit(
            db_session,
            scope=RateLimitScope.USER,
            scope_id=target,
            model_alias=None,
            data=RateLimitSetRequest(rpm_limit=100),
            actor=actor,
            ctx=ctx,
        )

    leader = leader_actor(admin_id, team_id)
    result = await service.list_limits(
        db_session,
        scope=RateLimitScope.USER,
        scope_id=member_id,
        model_alias=None,
        actor=leader,
    )

    assert [item.scope_id for item in result.items] == [str(member_id)]


async def test_leader_list_rejects_out_of_scope_target(db_session, cache_mgr, ctx):
    """권한 밖 대상은 빈 목록이 아니라 403 입니다."""
    team_id, admin_id, _, actor = await _fixtures(db_session)
    other_team = await seed_team(db_session, name="other-team")
    outsider = await seed_user(db_session, other_team, display_name="outsider")

    with pytest.raises(ForbiddenError):
        await RateLimitService(cache_mgr).list_limits(
            db_session,
            scope=RateLimitScope.USER,
            scope_id=outsider,
            model_alias=None,
            actor=leader_actor(admin_id, team_id),
        )
