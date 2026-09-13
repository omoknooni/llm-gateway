"""매핑 공통.

enum 은 backend 가 만든 PostgreSQL native 타입을 가리키기만 합니다(`create_type=False`).
값 집합이 갈리면 조회가 조용히 빈 결과를 내므로, 여기 정의는 backend 의
`src/app/models/enums.py` 와 같아야 합니다.
"""

from __future__ import annotations

import enum

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase

# 방언은 도메인 개념이라 core 가 정의합니다. 여기서는 그 값으로 PostgreSQL enum 을 가리키기만
# 합니다 — 정의가 둘로 갈리면 집계 값이 어긋납니다.
from gateway.core.dialect import ApiDialect

__all__ = [
    "ApiDialect",
    "Base",
    "BudgetPeriod",
    "BudgetPolicy",
    "BudgetScope",
    "ModelStatus",
    "Provider",
    "RateLimitScope",
    "UsageStatus",
    "VKOwnerType",
    "VKStatus",
    "pg_enum",
]


class Base(DeclarativeBase):
    pass


class VKOwnerType(enum.StrEnum):
    TEAM = "TEAM"
    USER = "USER"


class VKStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    ROTATED = "ROTATED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Provider(enum.StrEnum):
    BEDROCK = "BEDROCK"
    #: S1 로 추가된 값. 전송 방식(HTTPS + bearer)과 IAM 네임스페이스(bedrock-mantle:)가 다릅니다.
    BEDROCK_MANTLE = "BEDROCK_MANTLE"


class ModelStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BudgetScope(enum.StrEnum):
    """예산에는 VIRTUAL_KEY 가 없습니다 — VK 는 인증 수단이지 비용 주체가 아닙니다."""

    TEAM = "TEAM"
    USER = "USER"


class BudgetPeriod(enum.StrEnum):
    MONTHLY = "MONTHLY"


class BudgetPolicy(enum.StrEnum):
    HARD_BLOCK = "HARD_BLOCK"
    SOFT_WARN = "SOFT_WARN"


class RateLimitScope(enum.StrEnum):
    """예산과 달리 VIRTUAL_KEY 가 있습니다 — 팀 공용 키 하나가 팀 전체 속도를 잡아먹는 것을
    막아야 합니다(backend 06)."""

    GLOBAL = "GLOBAL"
    TEAM = "TEAM"
    USER = "USER"
    VIRTUAL_KEY = "VIRTUAL_KEY"


class UsageStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


def pg_enum(py_enum: type[enum.Enum], name: str, schema: str):
    return postgresql.ENUM(
        py_enum,
        name=name,
        schema=schema,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )
