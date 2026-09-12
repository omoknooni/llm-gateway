"""backend 스키마의 매핑.

**gateway 는 스키마를 정의하지 않습니다.** Alembic 의 단일 소유자는 backend 이고, 이 패키지는
같은 테이블을 읽기 위한(그리고 계약이 허용한 일부를 쓰기 위한) 매핑일 뿐입니다.
이 메타데이터로 DDL 을 실행하는 코드가 저장소에 있어서는 안 되며, 테스트가 그것을 막습니다.

필요한 컬럼만 매핑합니다. 전부 옮겨 적으면 backend 가 컬럼 하나를 바꿀 때마다 여기가 깨지고,
정작 우리가 의존하는 것이 무엇인지 읽히지 않습니다.

권한 범위는 backend/docs/08-shared-contracts.md C4:

    auth    SELECT + virtual_keys.last_used_at UPDATE
    model   SELECT
    budget  SELECT + budget_usages UPSERT
    usage   usage_events / auth_events INSERT
    audit   접근 없음
"""

from gateway.schema.auth import Team, User, VirtualKey, VirtualKeyAllowedModel
from gateway.schema.base import Base
from gateway.schema.budget import BudgetConfig, BudgetUsage
from gateway.schema.model import (
    ModelAlias,
    ModelPricing,
    RateLimitConfig,
    TeamAllowedModel,
    UserAllowedModel,
)
from gateway.schema.usage import AuthEvent, UsageEvent

__all__ = [
    "AuthEvent",
    "Base",
    "BudgetConfig",
    "BudgetUsage",
    "ModelAlias",
    "ModelPricing",
    "RateLimitConfig",
    "Team",
    "TeamAllowedModel",
    "UsageEvent",
    "User",
    "UserAllowedModel",
    "VirtualKey",
    "VirtualKeyAllowedModel",
]
