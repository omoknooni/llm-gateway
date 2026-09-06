"""테스트 공통 픽스처.

통합 테스트는 실제 PostgreSQL/Redis 를 씁니다(SQLite 로 대체하지 않습니다 — enum, 배열 컬럼,
partial unique index 가 전부 PostgreSQL 고유 기능이라 대체 DB 에서는 검증 가치가 없습니다).
여기 있는 것은 의존성 없이 도는 단위 테스트용 픽스처뿐입니다.
"""

from __future__ import annotations

import pytest

from gateway.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://gateway_app:x@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        log_format="console",
    )
