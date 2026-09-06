"""SQLAlchemy 선언 기반 클래스.

이 metadata 가 Alembic autogenerate 의 대상입니다. ORM 모델이 스키마 정의의 원천이고,
마이그레이션은 `backend/db/` 컴포넌트가 소유합니다(01 문서).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
