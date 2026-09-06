"""usage 스키마 — 원천 이벤트와 집계 테이블

Revision ID: 0002
Revises: '0001'
Create Date: 2026-09-06

usage_events 는 gateway 가 INSERT 하고 backend 는 읽기만 합니다. 스키마는 backend 가
정의하지만 컬럼 내용은 gateway 와의 합의 대상입니다(08 문서 C5).
월 단위 range 파티셔닝 도입 시점은 미결정입니다(07 문서 미결정 #3).
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = '0001'
branch_labels = None
depends_on = None

STATEMENTS: list[str] = [
    """CREATE TABLE usage.daily_usage_aggregates (
	bucket_date DATE NOT NULL,
	team_id UUID NOT NULL,
	user_id UUID NOT NULL,
	virtual_key_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	request_count BIGINT DEFAULT '0' NOT NULL,
	success_count BIGINT DEFAULT '0' NOT NULL,
	error_count BIGINT DEFAULT '0' NOT NULL,
	input_tokens BIGINT DEFAULT '0' NOT NULL,
	output_tokens BIGINT DEFAULT '0' NOT NULL,
	cache_write_tokens BIGINT DEFAULT '0' NOT NULL,
	cache_read_tokens BIGINT DEFAULT '0' NOT NULL,
	estimated_cost_usd NUMERIC(14, 6) DEFAULT '0' NOT NULL,
	avg_latency_ms INTEGER DEFAULT '0' NOT NULL,
	p95_latency_ms INTEGER DEFAULT '0' NOT NULL,
	aggregated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (bucket_date, team_id, user_id, virtual_key_id, model_alias)
)""",

    """CREATE TABLE usage.monthly_usage_aggregates (
	period VARCHAR(7) NOT NULL,
	team_id UUID NOT NULL,
	user_id UUID NOT NULL,
	virtual_key_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	request_count BIGINT DEFAULT '0' NOT NULL,
	success_count BIGINT DEFAULT '0' NOT NULL,
	error_count BIGINT DEFAULT '0' NOT NULL,
	input_tokens BIGINT DEFAULT '0' NOT NULL,
	output_tokens BIGINT DEFAULT '0' NOT NULL,
	cache_write_tokens BIGINT DEFAULT '0' NOT NULL,
	cache_read_tokens BIGINT DEFAULT '0' NOT NULL,
	estimated_cost_usd NUMERIC(14, 6) DEFAULT '0' NOT NULL,
	avg_latency_ms INTEGER DEFAULT '0' NOT NULL,
	p95_latency_ms INTEGER DEFAULT '0' NOT NULL,
	aggregated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (period, team_id, user_id, virtual_key_id, model_alias)
)""",

    """CREATE TABLE usage.usage_events (
	id UUID NOT NULL,
	request_id VARCHAR(128) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	team_id UUID NOT NULL,
	user_id UUID,
	virtual_key_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	provider_model_id VARCHAR(512) NOT NULL,
	dialect model.api_dialect NOT NULL,
	status usage.usage_status NOT NULL,
	input_tokens INTEGER DEFAULT '0' NOT NULL,
	output_tokens INTEGER DEFAULT '0' NOT NULL,
	cache_write_tokens INTEGER DEFAULT '0' NOT NULL,
	cache_read_tokens INTEGER DEFAULT '0' NOT NULL,
	estimated_usage BOOLEAN DEFAULT 'false' NOT NULL,
	latency_ms INTEGER NOT NULL,
	ttft_ms INTEGER,
	is_streaming BOOLEAN DEFAULT 'false' NOT NULL,
	estimated_cost_usd NUMERIC(14, 6) DEFAULT '0' NOT NULL,
	pricing_id UUID,
	error_code VARCHAR(64),
	PRIMARY KEY (id),
	UNIQUE (request_id),
	FOREIGN KEY(team_id) REFERENCES auth.teams (id),
	FOREIGN KEY(user_id) REFERENCES auth.users (id),
	FOREIGN KEY(virtual_key_id) REFERENCES auth.virtual_keys (id),
	FOREIGN KEY(pricing_id) REFERENCES model.model_pricings (id)
)""",

    "CREATE INDEX ix_usage_events_model_occurred ON usage.usage_events (model_alias, occurred_at)",

    "CREATE INDEX ix_usage_events_occurred_at ON usage.usage_events (occurred_at)",

    "CREATE INDEX ix_usage_events_team_occurred ON usage.usage_events (team_id, occurred_at)",

    "CREATE INDEX ix_usage_events_user_occurred ON usage.usage_events (user_id, occurred_at)",

    "CREATE INDEX ix_usage_events_vk_occurred ON usage.usage_events (virtual_key_id, occurred_at)",
]

DROP_TABLES: list[str] = [
    "usage.daily_usage_aggregates",

    "usage.monthly_usage_aggregates",

    "usage.usage_events",
]


def upgrade() -> None:
    for ddl in STATEMENTS:
        op.execute(ddl)


def downgrade() -> None:
    for table in reversed(DROP_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

