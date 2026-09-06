"""감사 로그.

control plane 의 **모든 상태 변경**을 기록합니다. 조회는 기록하지 않습니다.

기록은 **업무 트랜잭션과 같은 세션에 INSERT** 합니다. 업무가 롤백되면 감사도 롤백됩니다.
참조 구현은 비동기 큐 + 배치 flush 를 쓰지만, 감사 유실은 "누가 키를 폐기했는가"를 답하지
못하게 만들어 03 문서의 감사 요구사항을 깨므로 동기 INSERT 를 택했습니다(00 문서).
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILURE = "FAILURE"


class AuditActor(Protocol):
    """감사 주체. `CurrentAdmin` 이 구조적으로 만족합니다."""

    user_id: uuid.UUID
    role: Any


#: 시스템(주기 작업)이 주체일 때 쓰는 고정 UUID. 사람 계정과 섞이지 않게 예약값을 씁니다.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_ACTOR_ROLE = "SYSTEM"


async def record(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    changes: dict[str, Any] | None = None,
    result: str = RESULT_SUCCESS,
    ip_address: str | None = None,
    request_id: str = "",
) -> AuditLog:
    """감사 로그를 세션에 추가합니다. 커밋은 호출자(service)가 합니다.

    `changes` 에 VK 원문, 토큰, 비밀값을 넣지 않습니다. 마스킹된 prefix 만 남깁니다.
    """
    entry = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        changes=changes or {},
        result=result,
        ip_address=ip_address,
        request_id=request_id,
    )
    session.add(entry)
    return entry


async def record_for(
    session: AsyncSession,
    actor: AuditActor,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    changes: dict[str, Any] | None = None,
    result: str = RESULT_SUCCESS,
    ip_address: str | None = None,
    request_id: str = "",
) -> AuditLog:
    """`AuditActor` 를 받는 편의 래퍼."""
    role = actor.role
    return await record(
        session,
        actor_user_id=actor.user_id,
        actor_role=getattr(role, "value", str(role)),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
        result=result,
        ip_address=ip_address,
        request_id=request_id,
    )


async def record_system(
    session: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    changes: dict[str, Any] | None = None,
) -> AuditLog:
    """주기 작업이 주체인 기록."""
    return await record(
        session,
        actor_user_id=SYSTEM_ACTOR_ID,
        actor_role=SYSTEM_ACTOR_ROLE,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        changes=changes,
    )
