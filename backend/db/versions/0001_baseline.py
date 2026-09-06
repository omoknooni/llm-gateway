"""baseline — 스키마 5종의 전체 테이블, enum, 인덱스, 제약

Revision ID: 0001
Revises: None
Create Date: 2026-09-06

01 문서(backend/docs/01-data-model.md)의 데이터 모델을 그대로 옮긴 기준선입니다.
스키마·확장·DB 역할·GRANT 는 이 리비전이 아니라 db/init/*.sql 이 만듭니다.
DDL 은 모델에서 생성한 뒤 사람이 검토해 고정한 정적 SQL 입니다. 모델이 바뀌어도
이 리비전은 바뀌지 않습니다(기준선이 미래 모델을 따라가면 마이그레이션이 아닙니다).
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ENUM_TYPES: list[str] = [
    "CREATE TYPE auth.user_role AS ENUM ('ADMIN', 'TEAM_LEADER', 'MEMBER')",

    "CREATE TYPE auth.vk_owner_type AS ENUM ('TEAM', 'USER')",

    "CREATE TYPE auth.vk_status AS ENUM ('ACTIVE', 'ROTATED', 'REVOKED', 'EXPIRED')",

    "CREATE TYPE model.provider AS ENUM ('BEDROCK')",

    "CREATE TYPE model.api_dialect AS ENUM ('OPENAI_CHAT', 'ANTHROPIC_MESSAGES')",

    "CREATE TYPE model.model_status AS ENUM ('ACTIVE', 'INACTIVE')",

    "CREATE TYPE model.rate_limit_scope AS ENUM ('GLOBAL', 'TEAM', 'USER', 'VIRTUAL_KEY')",

    "CREATE TYPE budget.budget_scope AS ENUM ('TEAM', 'USER')",

    "CREATE TYPE budget.budget_period AS ENUM ('MONTHLY')",

    "CREATE TYPE budget.budget_policy AS ENUM ('HARD_BLOCK', 'SOFT_WARN')",

    "CREATE TYPE usage.usage_status AS ENUM ('SUCCESS', 'ERROR', 'TIMEOUT')",
]

STATEMENTS: list[str] = [
    """CREATE TABLE audit.audit_logs (
	id UUID NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	actor_user_id UUID NOT NULL,
	actor_role VARCHAR(32) NOT NULL,
	action VARCHAR(128) NOT NULL,
	resource_type VARCHAR(64) NOT NULL,
	resource_id VARCHAR(256) NOT NULL,
	changes JSONB DEFAULT '{}' NOT NULL,
	result VARCHAR(16) DEFAULT 'SUCCESS' NOT NULL,
	ip_address INET,
	request_id VARCHAR(128) DEFAULT '' NOT NULL,
	PRIMARY KEY (id)
)""",

    "CREATE INDEX ix_audit_logs_actor ON audit.audit_logs (actor_user_id, occurred_at)",

    "CREATE INDEX ix_audit_logs_occurred_at ON audit.audit_logs (occurred_at)",

    "CREATE INDEX ix_audit_logs_resource ON audit.audit_logs (resource_type, resource_id, occurred_at)",

    """CREATE TABLE audit.cache_invalidation_failures (
	id UUID NOT NULL,
	cache_key VARCHAR(512) NOT NULL,
	failed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	retry_count INTEGER DEFAULT '0' NOT NULL,
	last_retry_at TIMESTAMP WITH TIME ZONE,
	resolved_at TIMESTAMP WITH TIME ZONE,
	context JSONB DEFAULT '{}' NOT NULL,
	PRIMARY KEY (id)
)""",

    "CREATE INDEX ix_cache_failures_unresolved ON audit.cache_invalidation_failures (resolved_at, failed_at)",

    """CREATE TABLE auth.admin_jwt_configs (
	id UUID NOT NULL,
	issuer VARCHAR(512) NOT NULL,
	audience VARCHAR(512) NOT NULL,
	public_key_pem TEXT NOT NULL,
	algorithm VARCHAR(16) NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)""",

    """CREATE TABLE auth.teams (
	id UUID NOT NULL,
	name VARCHAR(255) NOT NULL,
	description TEXT,
	leader_user_id UUID,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name)
)""",

    """CREATE TABLE budget.budget_usages (
	scope budget.budget_scope NOT NULL,
	scope_id UUID NOT NULL,
	period VARCHAR(7) NOT NULL,
	used_usd NUMERIC(14, 4) DEFAULT '0' NOT NULL,
	limit_usd NUMERIC(14, 4) NOT NULL,
	notified_thresholds INTEGER[] DEFAULT '{}' NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (scope, scope_id, period),
	CONSTRAINT ck_budget_usage_period_format CHECK (period ~ '^[0-9]{4}-[0-9]{2}$')
)""",

    """CREATE TABLE auth.users (
	id UUID NOT NULL,
	email CITEXT NOT NULL,
	display_name VARCHAR(255) NOT NULL,
	role auth.user_role NOT NULL,
	team_id UUID,
	idp_subject VARCHAR(512),
	provider VARCHAR(64) DEFAULT 'local' NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	last_login_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (email),
	FOREIGN KEY(team_id) REFERENCES auth.teams (id),
	UNIQUE (idp_subject)
)""",

    "CREATE INDEX ix_users_team_id_active ON auth.users (team_id) WHERE is_active",

    """CREATE TABLE auth.service_tokens (
	id UUID NOT NULL,
	name VARCHAR(128) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	token_prefix VARCHAR(24) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	rotated_from_id UUID,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (token_hash),
	FOREIGN KEY(rotated_from_id) REFERENCES auth.service_tokens (id),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    """CREATE TABLE auth.virtual_keys (
	id UUID NOT NULL,
	name VARCHAR(255) NOT NULL,
	key_hash VARCHAR(64) NOT NULL,
	key_prefix VARCHAR(32) NOT NULL,
	owner_type auth.vk_owner_type NOT NULL,
	owner_id UUID NOT NULL,
	team_id UUID NOT NULL,
	status auth.vk_status NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE,
	last_used_at TIMESTAMP WITH TIME ZONE,
	rotated_from_id UUID,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_by UUID,
	revoke_reason VARCHAR(64),
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (key_hash),
	FOREIGN KEY(team_id) REFERENCES auth.teams (id),
	FOREIGN KEY(rotated_from_id) REFERENCES auth.virtual_keys (id),
	FOREIGN KEY(revoked_by) REFERENCES auth.users (id),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    "CREATE INDEX ix_virtual_keys_owner ON auth.virtual_keys (owner_type, owner_id)",

    "CREATE INDEX ix_virtual_keys_team_status ON auth.virtual_keys (team_id, status)",

    """CREATE TABLE budget.budget_configs (
	id UUID NOT NULL,
	scope budget.budget_scope NOT NULL,
	scope_id UUID NOT NULL,
	limit_usd NUMERIC(14, 4) NOT NULL,
	period_type budget.budget_period NOT NULL,
	policy budget.budget_policy NOT NULL,
	warn_thresholds INTEGER[] DEFAULT '{80,90,100}' NOT NULL,
	effective_from DATE NOT NULL,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_budget_limit_non_negative CHECK (limit_usd >= 0),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    "CREATE UNIQUE INDEX uq_budget_config_active ON budget.budget_configs (scope, scope_id) WHERE is_active",

    """CREATE TABLE model.model_aliases (
	alias VARCHAR(128) NOT NULL,
	display_name VARCHAR(128),
	provider model.provider NOT NULL,
	provider_model_id VARCHAR(512) NOT NULL,
	region VARCHAR(64),
	supported_dialects model.api_dialect[] NOT NULL,
	status model.model_status NOT NULL,
	max_input_tokens INTEGER,
	max_output_tokens INTEGER,
	supports_streaming BOOLEAN DEFAULT 'true' NOT NULL,
	description TEXT,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (alias),
	CONSTRAINT ck_model_alias_format CHECK (alias ~ '^[a-z0-9][a-z0-9.-]{1,127}$'),
	CONSTRAINT ck_model_dialects_not_empty CHECK (array_length(supported_dialects, 1) >= 1),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    """CREATE TABLE auth.virtual_key_allowed_models (
	virtual_key_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (virtual_key_id, model_alias),
	FOREIGN KEY(virtual_key_id) REFERENCES auth.virtual_keys (id) ON DELETE CASCADE,
	FOREIGN KEY(model_alias) REFERENCES model.model_aliases (alias)
)""",

    """CREATE TABLE model.model_pricings (
	id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	input_price_per_1k NUMERIC(14, 8) NOT NULL,
	output_price_per_1k NUMERIC(14, 8) NOT NULL,
	cache_write_price_per_1k NUMERIC(14, 8) DEFAULT '0' NOT NULL,
	cache_read_price_per_1k NUMERIC(14, 8) DEFAULT '0' NOT NULL,
	currency VARCHAR(3) DEFAULT 'USD' NOT NULL,
	effective_from TIMESTAMP WITH TIME ZONE NOT NULL,
	effective_until TIMESTAMP WITH TIME ZONE,
	source VARCHAR(32) NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_pricing_non_negative CHECK (input_price_per_1k >= 0 AND output_price_per_1k >= 0),
	CONSTRAINT ck_pricing_period_order CHECK (effective_until IS NULL OR effective_until > effective_from),
	FOREIGN KEY(model_alias) REFERENCES model.model_aliases (alias),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    "CREATE INDEX ix_model_pricings_alias_from ON model.model_pricings (model_alias, effective_from)",

    """CREATE TABLE model.rate_limit_configs (
	id UUID NOT NULL,
	scope model.rate_limit_scope NOT NULL,
	scope_id UUID,
	model_alias VARCHAR(128),
	rpm_limit INTEGER,
	tpm_limit INTEGER,
	concurrency_limit INTEGER,
	is_active BOOLEAN DEFAULT 'true' NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_rate_limit_not_empty CHECK (rpm_limit IS NOT NULL OR tpm_limit IS NOT NULL OR concurrency_limit IS NOT NULL),
	CONSTRAINT ck_rate_limit_positive CHECK ((rpm_limit IS NULL OR rpm_limit > 0) AND (tpm_limit IS NULL OR tpm_limit > 0) AND (concurrency_limit IS NULL OR concurrency_limit > 0)),
	CONSTRAINT ck_rate_limit_scope_id CHECK ((scope = 'GLOBAL' AND scope_id IS NULL) OR (scope <> 'GLOBAL' AND scope_id IS NOT NULL)),
	FOREIGN KEY(model_alias) REFERENCES model.model_aliases (alias),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    "CREATE UNIQUE INDEX uq_rate_limit_active ON model.rate_limit_configs (scope, COALESCE(scope_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(model_alias, '*')) WHERE is_active",

    """CREATE TABLE model.team_allowed_models (
	team_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (team_id, model_alias),
	FOREIGN KEY(team_id) REFERENCES auth.teams (id) ON DELETE CASCADE,
	FOREIGN KEY(model_alias) REFERENCES model.model_aliases (alias),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    """CREATE TABLE model.user_allowed_models (
	user_id UUID NOT NULL,
	model_alias VARCHAR(128) NOT NULL,
	created_by UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id, model_alias),
	FOREIGN KEY(user_id) REFERENCES auth.users (id) ON DELETE CASCADE,
	FOREIGN KEY(model_alias) REFERENCES model.model_aliases (alias),
	FOREIGN KEY(created_by) REFERENCES auth.users (id)
)""",

    "ALTER TABLE auth.teams ADD CONSTRAINT fk_teams_leader_user_id FOREIGN KEY(leader_user_id) REFERENCES auth.users (id)",

    "ALTER TABLE model.model_pricings ADD CONSTRAINT ex_model_pricings_no_overlap EXCLUDE USING gist (model_alias WITH =, tstzrange(effective_from, effective_until) WITH &&)",
]

DROP_TABLES: list[str] = [
    "audit.audit_logs",

    "audit.cache_invalidation_failures",

    "auth.admin_jwt_configs",

    "auth.teams",

    "budget.budget_usages",

    "auth.users",

    "auth.service_tokens",

    "auth.virtual_keys",

    "budget.budget_configs",

    "model.model_aliases",

    "auth.virtual_key_allowed_models",

    "model.model_pricings",

    "model.rate_limit_configs",

    "model.team_allowed_models",

    "model.user_allowed_models",
]

DROP_ENUMS: list[str] = [
    "auth.user_role",

    "auth.vk_owner_type",

    "auth.vk_status",

    "model.provider",

    "model.api_dialect",

    "model.model_status",

    "model.rate_limit_scope",

    "budget.budget_scope",

    "budget.budget_period",

    "budget.budget_policy",

    "usage.usage_status",
]


def upgrade() -> None:
    for ddl in ENUM_TYPES:
        op.execute(ddl)
    for ddl in STATEMENTS:
        op.execute(ddl)


def downgrade() -> None:
    for table in reversed(DROP_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for enum_type in DROP_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")

