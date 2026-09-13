"""배분 불변식이 동시 갱신에서도 유지되는지 (M6 리뷰 P1-1).

이 테스트가 필요한 이유는 검증이 **읽는 행과 쓰는 행이 다르기** 때문입니다. 팀 한도와 기존
배분을 읽고 그와 다른 사용자의 행을 INSERT 하므로, 행 잠금으로는 막히지 않는 write skew 가
생깁니다. PostgreSQL 없이는 재현조차 할 수 없어 단위 테스트로 대체할 수 없습니다.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import ConflictError
from app.models.budget import BudgetConfig
from app.models.enums import BudgetScope
from app.schemas.budgets import BudgetSetRequest
from app.services.budget_service import BudgetService
from tests.integration.conftest import admin_actor, seed_team, seed_user


async def _active_allocation_total(session_factory, team_id) -> Decimal:
    async with session_factory() as session:
        from app.models.auth import User

        stmt = (
            select(func.coalesce(func.sum(BudgetConfig.limit_usd), 0))
            .select_from(BudgetConfig)
            .join(User, User.id == BudgetConfig.scope_id)
            .where(
                BudgetConfig.scope == BudgetScope.USER,
                BudgetConfig.is_active.is_(True),
                User.team_id == team_id,
            )
        )
        return Decimal((await session.execute(stmt)).scalar_one())


async def _set_user_budget(session_factory, cache_mgr, redis_client, *, user_id, actor, ctx, limit):
    """각 호출이 **자기 세션**을 씁니다. 같은 세션을 공유하면 동시성이 아닙니다."""
    async with session_factory() as session:
        service = BudgetService(cache_mgr, redis_client)
        return await service.set_user_budget(
            session,
            user_id=user_id,
            data=BudgetSetRequest(limit_usd=limit),
            actor=actor,
            ctx=ctx,
        )


async def test_concurrent_user_budgets_cannot_exceed_team_limit(
    db_session, session_factory, cache_mgr, redis_client, ctx
):
    """팀 한도 100 에 60 짜리 두 요청이 동시에 들어와도 합계는 100 을 넘지 않습니다.

    잠금이 없으면 둘 다 "현재 합계 0"을 읽고 각각 통과해 최종 합계가 120 이 됩니다.
    """
    team_id = await seed_team(db_session)
    admin_id = await seed_user(db_session, team_id, display_name="admin")
    user_a = await seed_user(db_session, team_id, display_name="a")
    user_b = await seed_user(db_session, team_id, display_name="b")
    actor = admin_actor(admin_id, team_id)

    service = BudgetService(cache_mgr, redis_client)
    await service.set_team_budget(
        db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="100"), actor=actor, ctx=ctx
    )

    results = await asyncio.gather(
        _set_user_budget(
            session_factory, cache_mgr, redis_client,
            user_id=user_a, actor=actor, ctx=ctx, limit="60",
        ),
        _set_user_budget(
            session_factory, cache_mgr, redis_client,
            user_id=user_b, actor=actor, ctx=ctx, limit="60",
        ),
        return_exceptions=True,
    )

    succeeded = [r for r in results if not isinstance(r, Exception)]
    rejected = [r for r in results if isinstance(r, ConflictError)]
    unexpected = [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)]

    assert not unexpected, f"예상하지 못한 예외: {unexpected}"
    assert len(succeeded) == 1, "하나만 통과해야 합니다"
    assert len(rejected) == 1
    assert rejected[0].code == "budget_limit_conflict"

    total = await _active_allocation_total(session_factory, team_id)
    assert total <= Decimal("100"), f"배분 합계가 팀 한도를 넘었습니다: {total}"


async def test_concurrent_allocation_replacements_keep_invariant(
    db_session, session_factory, cache_mgr, redis_client, ctx
):
    """배분 일괄 설정 두 건이 동시에 들어와도 최종 합계가 팀 한도 안입니다.

    전체 교체라 나중 것이 이깁니다. 잠금이 없으면 두 교체가 서로 다른 멤버 행을 남겨
    **양쪽 배분이 함께 살아남는** 상태가 됩니다.
    """
    from app.schemas.budgets import AllocationSetRequest

    team_id = await seed_team(db_session)
    admin_id = await seed_user(db_session, team_id, display_name="admin")
    user_a = await seed_user(db_session, team_id, display_name="a")
    user_b = await seed_user(db_session, team_id, display_name="b")
    actor = admin_actor(admin_id, team_id)

    service = BudgetService(cache_mgr, redis_client)
    await service.set_team_budget(
        db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="100"), actor=actor, ctx=ctx
    )

    async def replace(user_id, amount):
        async with session_factory() as session:
            return await BudgetService(cache_mgr, redis_client).set_allocation(
                session,
                team_id=team_id,
                data=AllocationSetRequest(allocations=[{"user_id": str(user_id), "limit_usd": amount}]),
                actor=actor,
                ctx=ctx,
            )

    results = await asyncio.gather(
        replace(user_a, "90"), replace(user_b, "90"), return_exceptions=True
    )
    unexpected = [r for r in results if isinstance(r, Exception)]
    assert not unexpected, f"예상하지 못한 예외: {unexpected}"

    total = await _active_allocation_total(session_factory, team_id)
    assert total == Decimal("90.0000"), f"전체 교체인데 양쪽이 살아남았습니다: {total}"


async def test_lowering_team_limit_below_allocation_is_rejected(
    db_session, cache_mgr, redis_client, ctx
):
    """이미 배분된 합계보다 낮은 팀 한도는 거절합니다 — 허용하면 하위 합이 상위를 넘습니다."""
    team_id = await seed_team(db_session)
    admin_id = await seed_user(db_session, team_id, display_name="admin")
    user_a = await seed_user(db_session, team_id, display_name="a")
    actor = admin_actor(admin_id, team_id)

    service = BudgetService(cache_mgr, redis_client)
    await service.set_team_budget(
        db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="100"), actor=actor, ctx=ctx
    )
    await service.set_user_budget(
        db_session, user_id=user_a, data=BudgetSetRequest(limit_usd="80"), actor=actor, ctx=ctx
    )

    with pytest.raises(ConflictError) as exc:
        await service.set_team_budget(
            db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="50"), actor=actor, ctx=ctx
        )
    assert exc.value.code == "budget_limit_conflict"


async def test_budget_update_closes_previous_row(db_session, cache_mgr, redis_client, ctx):
    """설정 변경은 UPDATE 가 아니라 '닫고 새로 넣기'입니다.

    partial unique index 가 활성 행을 scope 당 하나로 강제하므로, 순서가 틀리면 여기서
    막힙니다(01·05 문서).
    """
    team_id = await seed_team(db_session)
    admin_id = await seed_user(db_session, team_id, display_name="admin")
    actor = admin_actor(admin_id, team_id)
    service = BudgetService(cache_mgr, redis_client)

    await service.set_team_budget(
        db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="100"), actor=actor, ctx=ctx
    )
    await service.set_team_budget(
        db_session, team_id=team_id, data=BudgetSetRequest(limit_usd="200"), actor=actor, ctx=ctx
    )

    rows = (
        await db_session.execute(
            select(BudgetConfig).where(
                BudgetConfig.scope == BudgetScope.TEAM, BudgetConfig.scope_id == team_id
            )
        )
    ).scalars().all()

    assert len(rows) == 2, "이전 한도가 감사 목적으로 남아야 합니다"
    assert sum(1 for row in rows if row.is_active) == 1
    active = next(row for row in rows if row.is_active)
    assert active.limit_usd == Decimal("200.0000")
