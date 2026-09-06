"""도메인 enum.

PostgreSQL native enum 으로 매핑합니다. **값 추가는 마이그레이션으로, 값 삭제는 하지 않습니다**
(01 문서 공통 규약). 타입 생성은 마이그레이션이 하므로 모델 쪽은 `create_type=False` 입니다.
"""

from __future__ import annotations

import enum

from sqlalchemy.dialects import postgresql


class UserRole(enum.StrEnum):
    ADMIN = "ADMIN"
    TEAM_LEADER = "TEAM_LEADER"
    MEMBER = "MEMBER"


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
    #: Bedrock Mantle. 전송 방식(HTTPS + bearer)과 IAM 네임스페이스(`bedrock-mantle:`)가
    #: native 와 다른 별도 백엔드입니다. 권한 경계가 다른 것을 같은 값으로 묶으면
    #: IRSA 정책을 모델별로 나눌 수 없습니다(09 문서 S1).
    BEDROCK_MANTLE = "BEDROCK_MANTLE"


class ApiDialect(enum.StrEnum):
    OPENAI_CHAT = "OPENAI_CHAT"
    ANTHROPIC_MESSAGES = "ANTHROPIC_MESSAGES"


class ModelStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RateLimitScope(enum.StrEnum):
    GLOBAL = "GLOBAL"
    TEAM = "TEAM"
    USER = "USER"
    VIRTUAL_KEY = "VIRTUAL_KEY"


class BudgetScope(enum.StrEnum):
    TEAM = "TEAM"
    USER = "USER"


class BudgetPeriod(enum.StrEnum):
    MONTHLY = "MONTHLY"


class BudgetPolicy(enum.StrEnum):
    HARD_BLOCK = "HARD_BLOCK"
    SOFT_WARN = "SOFT_WARN"


class UsageStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


#: (python enum, PostgreSQL 타입 이름, 스키마) — 마이그레이션이 이 목록으로 타입을 만듭니다.
ENUM_TYPES: list[tuple[type[enum.Enum], str, str]] = [
    (UserRole, "user_role", "auth"),
    (VKOwnerType, "vk_owner_type", "auth"),
    (VKStatus, "vk_status", "auth"),
    (Provider, "provider", "model"),
    (ApiDialect, "api_dialect", "model"),
    (ModelStatus, "model_status", "model"),
    (RateLimitScope, "rate_limit_scope", "model"),
    (BudgetScope, "budget_scope", "budget"),
    (BudgetPeriod, "budget_period", "budget"),
    (BudgetPolicy, "budget_policy", "budget"),
    (UsageStatus, "usage_status", "usage"),
]


def pg_enum(py_enum: type[enum.Enum], name: str, schema: str, *, create_type: bool = False):
    """모델과 마이그레이션이 공유하는 enum 컬럼 타입."""
    return postgresql.ENUM(
        py_enum,
        name=name,
        schema=schema,
        create_type=create_type,
        values_callable=lambda e: [member.value for member in e],
    )
