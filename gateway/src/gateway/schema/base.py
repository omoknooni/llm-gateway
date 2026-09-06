"""매핑 공통.

enum 은 backend 가 만든 PostgreSQL native 타입을 가리키기만 합니다(`create_type=False`).
값 집합이 갈리면 조회가 조용히 빈 결과를 내므로, 여기 정의는 backend 의
`src/app/models/enums.py` 와 같아야 합니다.
"""

from __future__ import annotations

import enum

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase


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


class ApiDialect(enum.StrEnum):
    OPENAI_CHAT = "OPENAI_CHAT"
    ANTHROPIC_MESSAGES = "ANTHROPIC_MESSAGES"


class ModelStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


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
