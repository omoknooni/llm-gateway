"""S2·S3·S4 — gateway 요청 스키마 변경

Revision ID: 0005
Revises: '0004'
Create Date: 2026-09-06

gateway 브랜치가 요청하고 backend 가 수용한 세 건입니다.
(backend/docs/09-gateway-contract-response.md)

- S2: `model.model_aliases.endpoint_url` + Mantle 필수 CHECK
      "어디로 부르는가"는 alias 해석의 결과이므로 설정이 아니라 카탈로그가 소유합니다.
- S3: `usage.usage_events.client`
      도구별 사용량 분해. 인가 신호가 아니라 관측 라벨입니다. 인덱스는 집계 축이 확정되는
      M7 에서 붙입니다(쓰기 경로 테이블에 쓰이지 않을 인덱스를 미리 두지 않습니다).
- S4: `usage.auth_events` 신설
      정책 거절(401/403/429)의 기록 자리. provider 호출이 없었으므로 `usage_events` 에
      토큰·비용 0 인 행을 대량으로 만들지 않습니다.

`occurrence_count` / `first_occurred_at` 은 backend 가 더한 컬럼입니다. gateway 가 동일 출처의
연속 실패를 60초 창으로 묶어 한 행으로 기록하므로, 원안대로면 행 수를 세는 쿼리가 실제 실패
횟수보다 적게 나옵니다. 조회는 `SUM(occurrence_count)` 를 씁니다.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATEMENTS: list[str] = [
    # ── S2 ──
    "ALTER TABLE model.model_aliases ADD COLUMN endpoint_url VARCHAR(1024)",
    "ALTER TABLE model.model_aliases ADD CONSTRAINT ck_model_endpoint_required CHECK (provider <> 'BEDROCK_MANTLE' OR endpoint_url IS NOT NULL)",

    # ── S3 ──
    "ALTER TABLE usage.usage_events ADD COLUMN client TEXT",

    # ── S4 ──
    """CREATE TABLE usage.auth_events (
	id UUID NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	first_occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	occurrence_count INTEGER DEFAULT '1' NOT NULL,
	outcome TEXT NOT NULL,
	virtual_key_id UUID,
	key_hash_prefix VARCHAR(8),
	team_id UUID,
	user_id UUID,
	client TEXT,
	model_alias VARCHAR(128),
	source_ip INET,
	request_id VARCHAR(128) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_auth_events_count_positive CHECK (occurrence_count >= 1),
	CONSTRAINT ck_auth_events_window_order CHECK (occurred_at >= first_occurred_at),
	FOREIGN KEY(virtual_key_id) REFERENCES auth.virtual_keys (id),
	FOREIGN KEY(team_id) REFERENCES auth.teams (id),
	FOREIGN KEY(user_id) REFERENCES auth.users (id)
)""",
    "CREATE INDEX ix_auth_events_occurred_at ON usage.auth_events (occurred_at)",
    "CREATE INDEX ix_auth_events_vk_occurred ON usage.auth_events (virtual_key_id, occurred_at)",
    "CREATE INDEX ix_auth_events_hash_prefix_occurred ON usage.auth_events (key_hash_prefix, occurred_at)",

    # 테이블 단위 권한. init/03_grants.sql 의 ALTER DEFAULT PRIVILEGES 는 usage 스키마에
    # backend SELECT 만 주므로, gateway 의 INSERT 는 여기서 명시적으로 부여합니다.
    # (db/grants/01_table_grants.sql 과 같은 내용을 두는 이유: 새 DB 는 grants 단계가,
    #  기존 DB 는 이 마이그레이션이 각각 권한을 맞춥니다. 둘 다 멱등합니다.)
    "GRANT SELECT ON usage.auth_events TO backend_app",
    "GRANT INSERT, SELECT ON usage.auth_events TO gateway_app",
]

DROP_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS usage.auth_events CASCADE",
    "ALTER TABLE usage.usage_events DROP COLUMN IF EXISTS client",
    "ALTER TABLE model.model_aliases DROP CONSTRAINT IF EXISTS ck_model_endpoint_required",
    "ALTER TABLE model.model_aliases DROP COLUMN IF EXISTS endpoint_url",
]


def upgrade() -> None:
    for ddl in STATEMENTS:
        op.execute(ddl)


def downgrade() -> None:
    for ddl in DROP_STATEMENTS:
        op.execute(ddl)
