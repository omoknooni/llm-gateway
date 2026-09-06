# 01. Data Model

| 항목 | 값 |
|---|---|
| 소유자 | `backend/` (Alembic 단일 소유) |
| 공유 범위 | gateway가 같은 스키마를 **읽습니다**. 스키마 변경은 공유 계약 변경입니다 |
| 상위 기준 | [00-admin-api-architecture.md](00-admin-api-architecture.md), [docs/implementation-plan.md](../../docs/implementation-plan.md) |

## Ownership

- **Alembic 마이그레이션의 단일 소유자는 `backend/`입니다.** gateway는 같은 테이블을 읽고
  일부 컬럼을 쓰지만 스키마를 정의하지 않습니다.
- 마이그레이션은 앱 패키지 밖의 별도 컴포넌트 `backend/db/`에 둡니다(참조 구현과 같은 구성, 00 문서).
  리비전 파일은 `backend/db/versions/NNNN_slug.py`, 스키마·역할·GRANT 부트스트랩은 `backend/db/init/*.sql`입니다.
- 마이그레이션은 DDL 권한을 가진 별도 역할로 배포 시점에만 실행합니다. 런타임 역할(`backend_app`)에는
  DDL 권한을 주지 않습니다. 앱이 기동하면서 스키마를 고치지 않습니다.
- gateway가 쓰는 테이블(`usage.usage_events`, `auth.virtual_keys.last_used_at`)의 컬럼 변경은
  gateway 브랜치와 합의한 뒤 진행합니다. 이 문서에서 **[공유]** 로 표시합니다.
- autogenerate 결과를 그대로 커밋하지 않습니다. 생성된 마이그레이션은 사람이 읽고 다듬습니다.

## Common Conventions

| 규약 | 내용 |
|---|---|
| PK | UUID(v4). 애플리케이션에서 생성해 INSERT합니다(반환값 왕복 제거) |
| 시간 | `TIMESTAMPTZ`. 애플리케이션은 timezone-aware UTC만 다룹니다 |
| 금액 | `NUMERIC`. Python은 `Decimal`. float 금지 |
| 단가 | `NUMERIC(14, 8)` (1k 토큰당 USD). 소액 단가의 반올림 손실 방지 |
| 총액 | `NUMERIC(14, 4)` |
| enum | PostgreSQL enum 타입. 값 추가는 마이그레이션으로. **값 삭제는 하지 않습니다** |
| 삭제 | 원칙적으로 soft delete(`is_active`) 또는 상태 전이. 감사 대상 엔터티는 hard delete 금지 |
| 명명 | 테이블/컬럼 snake_case, 테이블은 복수형 |
| 감사 컬럼 | 상태 변경 대상은 `created_at`, `updated_at`, `created_by`를 갖습니다 |

## Schema Layout

PostgreSQL 스키마를 도메인별로 나눕니다. **plane별 최소 권한 GRANT의 단위**가 되기 때문입니다.

| 스키마 | 내용 | backend | gateway |
|---|---|---|---|
| `auth` | 팀, 사용자, Virtual Key | CRUD | SELECT + `virtual_keys.last_used_at` UPDATE |
| `model` | 모델 alias, 단가, 허용 모델, rate limit 설정 | CRUD | SELECT |
| `budget` | 예산 설정, 기간별 소진 | CRUD | SELECT + `budget_usages` UPSERT |
| `usage` | 사용량 원천 이벤트, 집계 | SELECT (+집계 작업의 집계 테이블 쓰기) | INSERT |
| `audit` | control plane 감사 로그, 캐시 무효화 실패 | CRUD | 접근 없음 |

DB 역할은 두 개입니다. `backend_app`, `gateway_app`. 각각 위 표대로만 GRANT하고,
마이그레이션은 별도의 소유자 역할로 실행합니다. GRANT 정의도 backend의 마이그레이션이 소유합니다.

## Enum Types

| 타입 | 값 |
|---|---|
| `auth.user_role` | `ADMIN`, `TEAM_LEADER`, `MEMBER` |
| `auth.vk_owner_type` | `TEAM`, `USER` |
| `auth.vk_status` | `ACTIVE`, `ROTATED`, `REVOKED`, `EXPIRED` |
| `model.provider` | `BEDROCK` |
| `model.api_dialect` | `OPENAI_CHAT`, `ANTHROPIC_MESSAGES` |
| `model.model_status` | `ACTIVE`, `INACTIVE` |
| `model.rate_limit_scope` | `GLOBAL`, `TEAM`, `USER`, `VIRTUAL_KEY` |
| `budget.budget_scope` | `TEAM`, `USER` |
| `budget.budget_period` | `MONTHLY` |
| `budget.budget_policy` | `HARD_BLOCK`, `SOFT_WARN` |
| `usage.usage_status` | `SUCCESS`, `ERROR`, `TIMEOUT` |

`provider`는 지금 `BEDROCK` 하나지만 enum으로 둡니다. provider 추상화 유지가 ADR-0001의
후속 조건이고, 나중에 컬럼 타입을 바꾸는 것보다 값을 추가하는 편이 싸기 때문입니다.

## Entity Relationship

```text
auth.teams ──< auth.users ──< auth.virtual_keys ──< auth.virtual_key_allowed_models
     │              │                 │
     │              │                 └──[owner]── auth.teams (owner_type=TEAM)
     │              │
     ├──< model.team_allowed_models >── model.model_aliases ──< model.model_pricings
     │              └──< model.user_allowed_models ──┘
     │
     ├──< budget.budget_configs ──(period)── budget.budget_usages
     └──< model.rate_limit_configs

usage.usage_events ──> usage.daily_usage_aggregates ──> usage.monthly_usage_aggregates
audit.audit_logs (모든 control plane 변경)
audit.cache_invalidation_failures
```

## auth schema

### auth.teams

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `name` | text NOT NULL UNIQUE | 표시명 |
| `description` | text NULL | |
| `leader_user_id` | uuid NULL FK → `auth.users.id` | 팀장. 순환 FK이므로 nullable + `DEFERRABLE` |
| `is_active` | bool NOT NULL DEFAULT true | |
| `created_at` / `updated_at` | timestamptz | |

부서(department) 계층은 두지 않습니다. 현재 문서가 요구하는 집계 축은 팀/사용자/VK/모델이며,
계층을 미리 넣으면 예산 배분과 인가 판정이 근거 없이 복잡해집니다. 필요해지면 `parent_team_id`
추가로 확장합니다(미결정 항목, 07 문서).

### auth.users

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `email` | citext NOT NULL UNIQUE | 사내 계정 이메일 |
| `display_name` | text NOT NULL | |
| `role` | `auth.user_role` NOT NULL DEFAULT `MEMBER` | |
| `team_id` | uuid NULL FK → `auth.teams.id` | 팀 미배정 허용 |
| `idp_subject` | text NULL UNIQUE | OIDC `sub` claim. 관리자 수동 생성 직후에는 NULL |
| `provider` | text NOT NULL DEFAULT `local` | 주체 출처. 예 `oidc:keycloak`. 다중 IdP 식별자 |
| `is_active` | bool NOT NULL DEFAULT true | 비활성 = 로그인 불가 + VK 인증 거부 |
| `last_login_at` | timestamptz NULL | |
| `created_at` / `updated_at` | timestamptz | |

인덱스: `(team_id) WHERE is_active`, `(email)`.

### auth.admin_jwt_configs

관리자 토큰 검증용 공개키 등록표입니다. 기동 시 `is_active` 행을 로드합니다(00 문서).

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | JWT `kid`로도 씁니다 |
| `issuer` | text NOT NULL | |
| `audience` | text NOT NULL | |
| `public_key_pem` | text NOT NULL | RS256 공개키 |
| `algorithm` | text NOT NULL DEFAULT `RS256` | |
| `is_active` | bool NOT NULL DEFAULT true | |
| `created_at` / `updated_at` | timestamptz | |

비밀키는 저장하지 않습니다. 이 테이블에는 공개키만 들어갑니다.

### auth.service_tokens

외부 시스템·배치가 Admin API를 호출할 때 쓰는 토큰입니다. 원문은 저장하지 않습니다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `name` | text NOT NULL | 용도 식별 |
| `token_hash` | char(64) NOT NULL UNIQUE | `sha256(raw)` |
| `token_prefix` | text NOT NULL | 표시용 |
| `expires_at` | timestamptz NOT NULL | |
| `revoked_at` | timestamptz NULL | |
| `rotated_from_id` | uuid NULL FK → `auth.service_tokens.id` | 로테이션 체인 |
| `created_by` | uuid NOT NULL FK → `auth.users.id` | |
| `created_at` | timestamptz | |

### auth.virtual_keys **[공유]**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `name` | text NOT NULL | 운영자가 알아보는 이름 |
| `key_hash` | char(64) NOT NULL UNIQUE | `sha256(raw_key)` hex. **인증 조회 키** |
| `key_prefix` | text NOT NULL | 예 `vk_live_a1b2c3` — UI 표시용 |
| `owner_type` | `auth.vk_owner_type` NOT NULL | `TEAM` \| `USER` |
| `owner_id` | uuid NOT NULL | `owner_type`에 따라 team 또는 user |
| `team_id` | uuid NOT NULL FK → `auth.teams.id` | 집계·인가용 비정규화 (USER 소유여도 소속 팀 고정) |
| `status` | `auth.vk_status` NOT NULL | |
| `expires_at` | timestamptz NULL | NULL = 무기한(정책상 비권장) |
| `last_used_at` | timestamptz NULL | **gateway가 UPDATE** |
| `rotated_from_id` | uuid NULL FK → `auth.virtual_keys.id` | 로테이션 전후 연결 |
| `revoked_at` | timestamptz NULL | |
| `revoked_by` | uuid NULL FK → `auth.users.id` | |
| `revoke_reason` | text NULL | |
| `created_by` | uuid NOT NULL FK → `auth.users.id` | |
| `created_at` / `updated_at` | timestamptz | |

- 인덱스: `UNIQUE(key_hash)`, `(owner_type, owner_id)`, `(team_id, status)`,
  `(expires_at) WHERE status = 'ACTIVE'`.
- **키 원문은 저장하지 않습니다.** 근거와 대안 비교는 03 문서.
- `last_used_at`은 gateway가 쓰는 유일한 `auth` 컬럼입니다. 매 요청 UPDATE가 아니라
  분 단위 스로틀링으로 쓰는 것을 gateway와 합의합니다.

### auth.virtual_key_allowed_models

VK 단위 허용 모델 축소. 행이 없으면 소유자 정책을 그대로 따릅니다(= "제한 없음"이 아니라 "축소 없음").

| 컬럼 | 타입 |
|---|---|
| `virtual_key_id` | uuid PK FK → `auth.virtual_keys.id` ON DELETE CASCADE |
| `model_alias` | text PK FK → `model.model_aliases.alias` |
| `created_at` | timestamptz |

## model schema

### model.model_aliases

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `alias` | text PK | client가 `model` 필드에 넣는 값 |
| `display_name` | text NULL | |
| `provider` | `model.provider` NOT NULL | |
| `provider_model_id` | text NOT NULL | Bedrock model id 또는 inference profile ARN |
| `region` | text NULL | 미지정 시 배포 기본 리전 |
| `supported_dialects` | `model.api_dialect[]` NOT NULL | ADR-0003. 모델별로 노출 방언이 다를 수 있음 |
| `status` | `model.model_status` NOT NULL DEFAULT `ACTIVE` | |
| `max_input_tokens` / `max_output_tokens` | int NULL | 검증·표시용 |
| `supports_streaming` | bool NOT NULL DEFAULT true | |
| `description` | text NULL | |
| `created_by` | uuid NOT NULL | |
| `created_at` / `updated_at` | timestamptz | |

`alias`를 PK로 둡니다. gateway의 요청 경로 조회 키가 alias이고, 캐시 키(`policy:model:{alias}`)도
alias이기 때문입니다. alias 변경은 지원하지 않고 새 alias 생성 + 구 alias 비활성으로 처리합니다.

### model.model_pricings

단가는 **시계열**입니다. 과거 사용량을 그 시점 단가로 재계산할 수 있어야 합니다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `model_alias` | text NOT NULL FK → `model.model_aliases.alias` | |
| `input_price_per_1k` | numeric(14,8) NOT NULL | |
| `output_price_per_1k` | numeric(14,8) NOT NULL | |
| `cache_write_price_per_1k` | numeric(14,8) NOT NULL DEFAULT 0 | |
| `cache_read_price_per_1k` | numeric(14,8) NOT NULL DEFAULT 0 | |
| `currency` | char(3) NOT NULL DEFAULT `USD` | |
| `effective_from` | timestamptz NOT NULL | |
| `effective_until` | timestamptz NULL | NULL = 현재 유효 |
| `source` | text NOT NULL | `MANUAL` \| `BEDROCK_ONDEMAND` |
| `created_by` | uuid NOT NULL | |
| `created_at` | timestamptz | |

- 같은 alias에 대해 유효 구간이 겹치면 안 됩니다. `btree_gist` + `EXCLUDE USING gist`로
  DB 레벨에서 막습니다. 애플리케이션 검증만으로는 동시 요청에서 겹칩니다.
- 단가 행은 수정하지 않습니다. 새 행을 넣고 이전 행의 `effective_until`을 닫습니다.

### model.team_allowed_models / model.user_allowed_models

| 컬럼 | 타입 |
|---|---|
| `team_id` (또는 `user_id`) | uuid PK FK ON DELETE CASCADE |
| `model_alias` | text PK FK → `model.model_aliases.alias` |
| `created_by` | uuid NOT NULL |
| `created_at` | timestamptz |

해석 규칙(04 문서에서 상세):

- `user_allowed_models`에 행이 있으면 **그 목록만** 허용하고 팀 정책을 덮어씁니다.
- 행이 0개면 팀 정책으로 폴백합니다. "전체 허용"이 아닙니다.
- `team_allowed_models`에 행이 0개면 카탈로그의 `ACTIVE` 모델 전체 허용입니다.

### model.rate_limit_configs

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `scope` | `model.rate_limit_scope` NOT NULL | |
| `scope_id` | uuid NULL | `GLOBAL`이면 NULL |
| `model_alias` | text NULL FK | NULL = 해당 scope의 모든 모델 |
| `rpm_limit` | int NULL | 분당 요청 수 |
| `tpm_limit` | int NULL | 분당 토큰 수 |
| `concurrency_limit` | int NULL | 동시 진행 요청 수 |
| `is_active` | bool NOT NULL DEFAULT true | |
| `created_by` | uuid NOT NULL | |
| `created_at` / `updated_at` | timestamptz | |

- 유일성: `UNIQUE (scope, scope_id, model_alias) WHERE is_active` — partial unique index.
  `scope_id`/`model_alias`가 NULL인 조합도 하나만 존재해야 하므로 `COALESCE` 표현식 인덱스를 씁니다.
- 세 한도가 모두 NULL인 행은 만들 수 없습니다(CHECK 제약). "제한 없음"은 행 삭제로 표현합니다.

## budget schema

### budget.budget_configs

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `scope` | `budget.budget_scope` NOT NULL | `TEAM` \| `USER` |
| `scope_id` | uuid NOT NULL | |
| `limit_usd` | numeric(14,4) NOT NULL CHECK ≥ 0 | |
| `period_type` | `budget.budget_period` NOT NULL DEFAULT `MONTHLY` | |
| `policy` | `budget.budget_policy` NOT NULL DEFAULT `HARD_BLOCK` | |
| `warn_thresholds` | int[] NOT NULL DEFAULT `{80,90,100}` | 경고 발송 기준(%) |
| `effective_from` | date NOT NULL | |
| `is_active` | bool NOT NULL DEFAULT true | |
| `created_by` | uuid NOT NULL | |
| `created_at` / `updated_at` | timestamptz | |

- 유일성: `UNIQUE (scope, scope_id) WHERE is_active`. 같은 대상에 활성 예산은 하나뿐입니다.
- 이력이 필요하므로 갱신 시 기존 행을 `is_active=false`로 닫고 새 행을 만듭니다.

### budget.budget_usages **[공유]**

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `scope` | `budget.budget_scope` PK | |
| `scope_id` | uuid PK | |
| `period` | char(7) PK | `YYYY-MM` (UTC 기준) |
| `used_usd` | numeric(14,4) NOT NULL DEFAULT 0 | 누적 소진액 |
| `limit_usd` | numeric(14,4) NOT NULL | 기간 시작 시점 한도 스냅샷 |
| `notified_thresholds` | int[] NOT NULL DEFAULT `{}` | 중복 알림 방지 |
| `updated_at` | timestamptz | |

- 이 테이블의 **쓰기 주체는 data plane 경로**입니다(gateway 또는 사용량 기록 작업).
  backend는 조회하고, 관리자 조작으로만 재시드합니다.
- Redis 카운터가 진실의 빠른 사본이고, 이 테이블이 **내구 사본**입니다. 두 값의 동기화 규칙은
  05 문서에서 정의합니다.

## usage schema

### usage.usage_events **[공유, gateway가 INSERT]**

스키마는 backend의 마이그레이션이 정의하지만 내용은 gateway가 결정합니다.
[usage-and-cost-observability.md](../../docs/usage-and-cost-observability.md)의 캡처 항목을 그대로 따릅니다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | uuid PK | |
| `request_id` | text NOT NULL UNIQUE | 중복 기록 방지 |
| `occurred_at` | timestamptz NOT NULL | 파티션 키 후보 |
| `team_id` / `virtual_key_id` | uuid NOT NULL | 집계 축 |
| `user_id` | uuid NULL | 집계 축. `TEAM` 소유 VK 호출은 사람에 귀속되지 않으므로 NULL |
| `model_alias` | text NOT NULL | |
| `provider_model_id` | text NOT NULL | |
| `dialect` | `model.api_dialect` NOT NULL | 방언 중립 집계를 위해 값으로 기록 |
| `status` | `usage.usage_status` NOT NULL | 실패도 집계 대상 |
| `input_tokens` / `output_tokens` | int NOT NULL DEFAULT 0 | |
| `cache_write_tokens` / `cache_read_tokens` | int NOT NULL DEFAULT 0 | |
| `estimated_usage` | bool NOT NULL DEFAULT false | provider 응답에 usage가 없어 추정한 경우 |
| `latency_ms` | int NOT NULL | |
| `ttft_ms` | int NULL | 스트리밍 |
| `is_streaming` | bool NOT NULL DEFAULT false | |
| `estimated_cost_usd` | numeric(14,6) NOT NULL DEFAULT 0 | 기록 시점 단가로 계산 |
| `pricing_id` | uuid NULL FK → `model.model_pricings.id` | 어떤 단가를 썼는지 추적 |
| `error_code` | text NULL | |

- 인덱스: `(occurred_at)`, `(team_id, occurred_at)`, `(user_id, occurred_at)`,
  `(virtual_key_id, occurred_at)`, `(model_alias, occurred_at)`.
- 월 단위 range 파티셔닝을 전제로 설계합니다(보존 정책과 대량 삭제를 위해).
  실제 파티션 도입 시점은 07 문서의 미결정 항목입니다.

### usage.daily_usage_aggregates / usage.monthly_usage_aggregates

집계 축(팀/사용자/VK/모델 × 기간)당 한 행. 대시보드와 리더보드는 **집계 테이블만** 읽습니다.

| 컬럼 | 타입 |
|---|---|
| `bucket_date` (또는 `period`) | date / char(7) PK |
| `team_id`, `user_id`, `virtual_key_id`, `model_alias` | 집계 축 PK 구성 |
| `request_count`, `success_count`, `error_count` | bigint |
| `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens` | bigint |
| `estimated_cost_usd` | numeric(14,6) |
| `avg_latency_ms`, `p95_latency_ms` | int |
| `aggregated_at` | timestamptz |

집계 작업은 backend의 주기 job이 소유합니다(원천 이벤트는 읽기만).

## audit schema

### audit.audit_logs

00 문서의 Audit Contract를 그대로 컬럼화합니다.

| 컬럼 | 타입 |
|---|---|
| `id` | uuid PK |
| `occurred_at` | timestamptz NOT NULL |
| `actor_user_id` | uuid NOT NULL |
| `actor_role` | text NOT NULL |
| `action` | text NOT NULL |
| `resource_type` | text NOT NULL |
| `resource_id` | text NOT NULL |
| `changes` | jsonb NOT NULL DEFAULT `{}` |
| `result` | text NOT NULL |
| `ip_address` | inet NULL |
| `request_id` | text NOT NULL |

인덱스: `(resource_type, resource_id, occurred_at DESC)`, `(actor_user_id, occurred_at DESC)`,
`(occurred_at DESC)`.

`virtual_key_audit_log`를 별도 테이블로 두지 않고 이 테이블에 `resource_type='virtual_key'`로
기록합니다. 감사 기록의 형식·보존·권한을 한 곳에서 관리하기 위해서입니다.
VK 감사 조회 API는 이 테이블을 필터링합니다(03 문서).

단, **인증 성공/실패 이벤트는 여기 들어오지 않습니다.** 그것은 data plane의 사건이고
`usage` 스키마가 받습니다. control plane 감사와 data plane 인증 로그를 섞지 않습니다.

### audit.cache_invalidation_failures

| 컬럼 | 타입 |
|---|---|
| `id` | uuid PK |
| `cache_key` | text NOT NULL |
| `failed_at` | timestamptz NOT NULL |
| `retry_count` | int NOT NULL DEFAULT 0 |
| `last_retry_at` | timestamptz NULL |
| `resolved_at` | timestamptz NULL |
| `context` | jsonb NOT NULL DEFAULT `{}` |

## Migration Plan

| 파일 | 내용 |
|---|---|
| `init/01_create_schemas.sql` | 스키마 5개, `pgcrypto`·`citext`·`btree_gist` 확장 |
| `init/02_create_roles.sql` | `backend_app` / `gateway_app` 역할 생성 (비밀번호는 환경변수) |
| `init/03_grants.sql` | 스키마 사용 권한 + `ALTER DEFAULT PRIVILEGES` (이후 마이그레이션 산출물에 자동 적용) |
| `versions/0001_baseline` | enum 전체, `auth`/`model`/`budget`/`audit` 테이블, 인덱스, 제약 |
| `versions/0002_usage_tables` | `usage.usage_events`, 집계 테이블 (gateway 착수 전 확정 필요) |
| `versions/0003_seed_bootstrap` | 기본 팀, 부트스트랩 관리자 사용자 행(`ADMIN_EMAILS` 기준) |
| `grants/01_table_grants.sql` | 테이블 단위 권한. 대상 테이블이 있어야 하므로 Alembic 이후에 적용 |

`run_migration.sh`가 `init/*.sql` → `alembic upgrade head` → `grants/*.sql` 순으로 실행합니다.
스키마 사용 권한과 테이블 단위 권한이 나뉘는 이유는, 전자는 테이블이 없어도 걸 수 있지만
후자는 대상 테이블이 존재해야 하기 때문입니다. init SQL은 멱등해야 합니다(`IF NOT EXISTS`).

- 마이그레이션은 **앞으로만** 갑니다. downgrade는 작성하되 운영에서 실행하지 않습니다.
- 데이터 백필이 필요한 마이그레이션은 스키마 변경과 분리합니다.
- `0002` 이전에 gateway 브랜치와 usage 이벤트 컬럼을 합의합니다. 이 합의가 Phase 2의 선행 조건입니다.

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| VK 저장 | AES-256-GCM 암호문(`key_value_encrypted`) | `sha256` 해시 + prefix | 원문 복호화가 필요한 유스케이스가 없습니다. 상세는 03 문서 |
| 조직 계층 | org → dept → team 3단 | team 단일 계층 | 문서가 요구하는 집계 축에 dept가 없습니다. 필요 시 확장 |
| 마이그레이션 컴포넌트 | 저장소 루트 `db/` | `backend/db/` (구성은 동일) | AGENTS.md 브랜치 규율과 마이그레이션 소유권 |
| 단가 테이블 | 5m/1h 캐시 단가 분리 | `cache_write` / `cache_read` 2종 | Bedrock 온디맨드 기준선. 세분화가 필요해지면 컬럼 추가 |
| 방언 | `api_format` 단일 값 | `supported_dialects` 배열 | ADR-0003. 한 모델이 두 방언으로 노출될 수 있어야 합니다 |
| usage 로그 | `client` 태그 등 제품 특화 컬럼 다수 | 방언·추정 여부·단가 추적 컬럼 | 우리 관측 요구사항 기준으로 재정의 |
