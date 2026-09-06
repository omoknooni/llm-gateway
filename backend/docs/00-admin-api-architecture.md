# 00. Admin API Architecture

| 항목 | 값 |
|---|---|
| 대상 | `backend/` (control plane, Admin API) |
| 브랜치 | `feat/admin-backend` |
| 상위 기준 | [AGENTS.md](../../AGENTS.md), [docs/implementation-plan.md](../../docs/implementation-plan.md) |
| 참조 구현 | `awsome-ai-gateway/admin-api` |

## Objective

Admin API는 llm-gateway 정책의 **source of truth**입니다. 팀/사용자/Virtual Key/모델 카탈로그/
예산/rate limit을 CRUD하고, 변경 사실을 gateway가 볼 수 있는 형태(DB + 캐시 무효화)로 전파합니다.
client의 추론 요청은 받지 않으며, 사용량 원천 이벤트를 쓰지도 않습니다.

이 문서는 서비스 경계, 레이어 구조, 관리자 인증/인가, 에러·감사·캐시 무효화 규약을 정의합니다.
개별 도메인의 스키마와 API는 01~06 문서에서 다룹니다.

## Service Boundary

```text
Admin (browser)
   │
   ▼
frontend (Next.js SSR / route handler)      ← 브라우저는 backend를 직접 호출하지 않음
   │  Authorization: Bearer <admin session token>
   ▼
backend (Admin API, FastAPI)
   ├─ write → PostgreSQL (auth / model / budget schema)
   ├─ read  → PostgreSQL (usage schema, 집계 테이블 우선)
   └─ DEL   → Redis (정책 캐시 키 무효화만)
                                        gateway ── 캐시 채움 / 카운터 증가 / usage 기록
```

경계 규칙:

- backend는 gateway를 호출하지 않고, gateway도 backend를 호출하지 않습니다. 두 plane은
  **DB 스키마와 Redis 키 규약**으로만 만납니다.
- backend는 Redis에 **값을 쓰지 않습니다**. 정책 변경 시 해당 캐시 키를 삭제만 하고,
  다음 요청에서 gateway가 DB를 읽어 채웁니다. (예외는 아래 "캐시 소유권"의 단일 항목)
- backend는 `usage.usage_events`에 INSERT하지 않습니다. 읽기만 합니다.
- backend는 Bedrock을 호출하지 않습니다. 모델 카탈로그는 사람이 등록하거나 별도 sync 작업이
  채웁니다(04 문서).

## Layering

```text
app/
├── main.py                 FastAPI 조립, lifespan, 예외 핸들러, 미들웨어
├── core/                   설정, DB/Redis 클라이언트, 인증, 감사, 캐시 무효화, 예외
├── models/                 SQLAlchemy ORM (스키마 정의의 원천)
├── schemas/                Pydantic 요청/응답 DTO
├── repositories/           쿼리 계층. 세션을 받고 트랜잭션을 열지 않음
├── services/               도메인 규칙. 트랜잭션 경계, 감사 기록, 캐시 무효화 트리거
├── routers/                HTTP 계층. 인증/인가 의존성, DTO 변환만
└── jobs/                   주기 작업 (키 만료, 사용량 집계, 캐시 무효화 재시도)
```

마이그레이션은 애플리케이션 패키지 밖의 **별도 컴포넌트**입니다. 참조 구현과 같은 구성입니다.

```text
backend/db/
├── alembic.ini
├── env.py
├── versions/               Alembic 리비전
├── init/                   스키마·역할·GRANT 부트스트랩 SQL
├── run_migration.sh        init SQL → alembic upgrade head
└── Dockerfile              마이그레이션 Job 전용 이미지
```

앱 이미지와 분리하는 이유는 권한이 다르기 때문입니다. 런타임은 `backend_app` 역할로 최소 권한만
갖고, 마이그레이션은 DDL 권한을 가진 별도 역할로 배포 시점에만 실행합니다.
앱이 기동하면서 스키마를 고치지 않습니다.

> 참조 구현은 이 컴포넌트를 저장소 루트의 `db/`에 둡니다. 우리는 `backend/db/`에 둡니다.
> 구성과 실행 방식은 같고, 위치만 AGENTS.md의 브랜치 규율(공용 디렉터리는 `main`에서 변경)과
> 마이그레이션 소유권(`backend/`)에 맞췄습니다.

규칙:

- **router는 도메인 규칙을 갖지 않습니다.** 인가 판정과 DTO 변환까지만 하고 service를 호출합니다.
- **service가 트랜잭션 경계입니다.** 하나의 요청은 하나의 트랜잭션으로 커밋하고, 커밋 이후에
  캐시 무효화를 수행합니다. 순서를 뒤집지 않습니다(캐시를 먼저 지우면 gateway가 옛 값을 다시 채웁니다).
- **repository는 세션을 만들지 않습니다.** service가 만든 세션을 받습니다.
- ORM 모델과 API 스키마를 같은 클래스로 겸용하지 않습니다.

### 의존성 주입

서비스 인스턴스는 lifespan에서 만들어 `app.state`에 둡니다. router는 `Depends`로 꺼내 씁니다.
DB 세션은 요청 스코프 의존성으로 주입하고, 백그라운드 작업은 자체 세션 팩토리를 씁니다.

## Admin Authentication

관리자 인증은 **참조 구현과 동일한 구성**을 따릅니다. 사내 SSO/IdP(OIDC)를 1차 경로로 두고,
자체 발급 Admin JWT와 서비스 토큰을 함께 수용합니다. 로컬 비밀번호 계정은 두지 않습니다.

```text
Authorization: Bearer <token>  |  Cookie: admin_session=<token>
          │
          ▼  core/auth.py: get_current_admin
   ┌──────┴───────────────────────────────────────────────┐
   │ 1. dev 토큰      (DEV_LOGIN_ENABLED=true 일 때만)      │
   │ 2. 서비스 토큰   (`svc-` 접두사 → auth.service_tokens) │
   │ 3. OIDC 토큰     (JWKS 서명 검증, issuer/audience)     │
   │ 4. Admin JWT     (auth.admin_jwt_configs 의 공개키)    │
   └──────┬───────────────────────────────────────────────┘
          ▼
   CurrentAdmin(user_id, email, role, team_id, is_service_token)
```

- **OIDC**: `OIDC_ISSUER_URL`의 discovery 문서에서 JWKS를 받아 서명을 검증합니다. JWKS는 TTL 캐시하고,
  `iss`/`aud`/`exp`를 검증합니다. claim 이름은 IdP마다 다르므로 설정값으로 흡수합니다
  (`OIDC_USER_ID_CLAIM`, `OIDC_EMAIL_CLAIM`, `OIDC_NAME_CLAIM`, `OIDC_GROUPS_CLAIM`).
- **Admin JWT**: `auth.admin_jwt_configs`에 issuer / audience / 공개키(PEM) / 알고리즘(RS256)을 등록하고
  기동 시 활성 설정을 로드합니다. 다중 IdP를 동시에 운영하거나 자체 토큰을 쓰는 경로입니다.
- **서비스 토큰**: 외부 시스템·배치가 호출할 때 씁니다. `svc-` 접두사 + 랜덤 값이고
  `auth.service_tokens`에 sha256 해시로만 저장합니다. 만료·폐기·로테이션을 지원하며,
  검증되면 ADMIN 권한의 합성 주체(`is_service_token=true`)가 됩니다. 감사 로그에 그대로 드러납니다.
- **dev 토큰**: `DEV_LOGIN_ENABLED=true`인 로컬 개발에서만 동작합니다. 운영 설정에서는 꺼지고,
  켜져 있으면 기동 시 경고 로그를 남깁니다.
- 사용자 매칭 키는 `auth.users.idp_subject`(기본 claim `sub`)이고, `auth.users.provider`에
  어느 IdP에서 온 주체인지 기록합니다. 역할 부트스트랩은 `ADMIN_EMAILS` / `ADMIN_GROUPS` 설정으로
  하고, 매칭되면 `ADMIN`을 부여합니다.
- **ADR 후보**: 사내 IdP 확정과 그룹 → 팀 매핑 규칙. 인증 *방식*은 OIDC로 확정했고,
  어느 IdP를 쓰고 그룹을 팀에 어떻게 대응시킬지는 남아 있습니다(07 문서 미결정 #1).

관리자 토큰은 Virtual Key와 **완전히 다른 자격 증명**입니다. VK로 Admin API를 호출할 수 없고,
관리자 토큰으로 gateway를 호출할 수 없습니다. 두 검증 경로는 코드를 공유하지 않습니다.

## Authorization

역할은 세 가지입니다.

| 역할 | 의미 |
|---|---|
| `ADMIN` | 플랫폼 운영자. 전 범위 |
| `TEAM_LEADER` | 자기 팀 범위의 조회와 제한된 쓰기 |
| `MEMBER` | 자기 자신에 관한 조회만 |

| 리소스 | ADMIN | TEAM_LEADER | MEMBER |
|---|---|---|---|
| 팀 CRUD | 전체 | 자기 팀 조회 | 자기 팀 조회 |
| 사용자 CRUD·팀 이동 | 전체 | 자기 팀 멤버 조회 | 자기 자신 조회 |
| VK 발급/폐기 | 전체 | 자기 팀 소유 VK | 자기 소유 VK 조회·폐기 |
| 모델 카탈로그 CRUD | 전체 | 조회 | 조회(허용 목록만) |
| 모델 단가 | 전체 | 없음 | 없음 |
| 팀 허용 모델 | 전체 | 자기 팀(관리자 지정 상한 내) | 없음 |
| 예산 설정 | 전체 | 자기 팀 예산의 **하위 배분**만 | 자기 소진율 조회 |
| rate limit 설정 | 전체 | 자기 팀 하위(팀 값 이하) | 자기 값 조회 |
| 사용량·비용 조회 | 전체 | 자기 팀 | 자기 자신 |
| 감사 로그 | 전체 | 자기 팀 리소스 | 없음 |

규칙:

- 인가는 **역할 + 대상 소유권** 두 축으로 판정합니다. `TEAM_LEADER`가 다른 팀 리소스를 지정하면
  404가 아니라 403을 반환합니다(존재 여부를 숨겨야 하는 리소스는 별도로 표시).
- 상한을 넘는 하위 설정은 거절합니다. 팀 예산 100달러를 팀장이 멤버들에게 120달러로 배분할 수 없습니다.
- 인가 판정은 router의 의존성에서 끝내지 않고, 소유권 검사가 필요한 경우 service가 다시 확인합니다.

## Error Contract

모든 실패 응답은 동일한 봉투를 사용합니다. frontend는 `code`로 분기합니다.

```json
{
  "error": {
    "code": "budget_limit_conflict",
    "message": "팀 예산 합계가 상위 예산을 초과합니다",
    "details": {"team_id": "...", "allocated_usd": "120.0000", "limit_usd": "100.0000"},
    "request_id": "0f9c..."
  }
}
```

| 예외 | 상태 | code 예시 |
|---|---|---|
| `ValidationError` | 400 | `validation_error` |
| 인증 실패 | 401 | `unauthenticated` |
| 인가 실패 | 403 | `forbidden` |
| `NotFoundError` | 404 | `not_found` |
| `ConflictError` | 409 | `conflict`, `duplicate_alias` |
| 상태 전이 위반 | 409 | `invalid_state_transition` |
| 그 외 | 500 | `internal_error` |

- `message`는 사람이 읽는 한국어 문장, `code`는 기계가 읽는 안정 식별자입니다. `code`는 계약이므로
  임의로 바꾸지 않습니다.
- 내부 예외 타입을 그대로 노출하지 않습니다. 스택트레이스는 로그에만 남깁니다.

## Audit Contract

control plane의 **모든 상태 변경**은 감사 로그를 남깁니다. 조회는 남기지 않습니다.

| 필드 | 내용 |
|---|---|
| `actor_user_id`, `actor_role` | 수행 주체 |
| `action` | `CREATE_VIRTUAL_KEY`, `REVOKE_VIRTUAL_KEY`, `SET_TEAM_BUDGET` 등 동사_명사 |
| `resource_type`, `resource_id` | 대상 |
| `changes` | `{"before": {...}, "after": {...}}` JSONB. 비밀값은 절대 넣지 않음 |
| `result` | `SUCCESS` / `FAILURE` |
| `ip_address`, `request_id` | 추적 정보 |

- 감사 기록은 **업무 트랜잭션과 같은 트랜잭션에서 INSERT**합니다. 업무가 롤백되면 감사도 롤백됩니다.
  큐에 넣어 비동기로 쓰지 않습니다.
- VK 원문, 비밀번호 해시, 토큰은 `changes`에 넣지 않습니다. 마스킹된 prefix만 남깁니다.
- 실패한 시도도 보안상 의미가 있는 경우(권한 없는 폐기 시도 등) `result=FAILURE`로 남깁니다.

### 참조 구현과의 차이

참조 구현은 감사 로그를 in-process asyncio 큐에 넣고 배치로 flush합니다(응답 지연 최소화 목적,
대신 eventually-consistent이고 pod 강제 종료 시 유실됩니다). 우리는 **동기 INSERT**를 택합니다.
control plane은 저 QPS이고, 감사 유실은 "누가 키를 폐기했는가"를 답하지 못하게 만들어
[virtual-key-management.md](../../docs/virtual-key-management.md)의 감사 요구사항을 깨기 때문입니다.
쓰기 부하가 문제가 되면 그때 배치로 되돌리고 ADR로 남깁니다.

## Cache Invalidation Contract

> **공유 계약** — 이 절의 키 이름은 gateway(`feat/gateway`)가 소유합니다. backend가 단독으로
> 바꿀 수 없고, 아래 목록은 gateway 브랜치와 합의해야 하는 **제안**입니다.

원칙은 하나입니다. **control plane은 지우기만 하고, 값은 gateway가 채웁니다.**

| 변경 | 삭제할 키(제안) |
|---|---|
| VK 발급/폐기/로테이션 | `vk:auth:{key_hash}` |
| 사용자 팀 이동 | 해당 사용자 소유 VK 전부의 `vk:auth:{key_hash}` |
| 팀/사용자 허용 모델 변경 | `policy:allowed_models:{scope}:{id}`, 영향 받는 `vk:auth:*` |
| 모델 alias 수정/비활성 | `policy:model:{alias}` |
| 모델 단가 변경 | `policy:model:{alias}` |
| 예산 설정 변경 | `policy:budget:{scope}:{id}` |
| rate limit 설정 변경 | `policy:ratelimit:{scope}:{id}:{model_alias\|*}` |

- **backend가 쓰지도 지우지도 않는 키**: 집행 카운터(`rl:*` rate limit 윈도, `budget:usage:*` 소진 카운터).
  이들은 gateway의 런타임 상태이며, backend는 화면 표시를 위해 **읽기만** 합니다. 유일한 예외는 05 문서에 정의한 "예산 소진값 재시드"
  운영 API이며, 명시적 관리자 조작이고 감사 로그를 남깁니다.
- 무효화는 **best-effort**입니다. Redis 오류로 삭제에 실패해도 업무 트랜잭션은 이미 커밋된 상태이므로
  롤백하지 않고 `audit.cache_invalidation_failures`에 기록합니다.
  `POST /api/v1/internal/cache/retry`가 미해결 항목을 재시도합니다.
- 실패가 남아도 gateway는 캐시 TTL 만료 시 스스로 최신 값을 읽습니다. 즉 무효화 실패의 영향은
  "정책 반영 지연"이지 "영구 불일치"가 아닙니다. TTL 상한은 gateway와 합의합니다.
- 팬아웃이 큰 무효화(팀 정책 변경 → 팀 멤버 VK 전부)는 `SCAN`으로 훑지 않고, DB에서 대상 키
  목록을 만들어 정확히 삭제합니다.

## API Conventions

- 베이스 경로는 `/api/v1`입니다. 파괴적 변경은 `/api/v2`로 분리합니다.
- 리소스 경로는 복수형 명사입니다: `/api/v1/teams`, `/api/v1/virtual-keys`, `/api/v1/models`.
- 목록 조회는 **cursor 기반 페이지네이션**을 씁니다. offset은 쓰지 않습니다.

  ```json
  {"items": [...], "next_cursor": "01H...", "has_more": true}
  ```

- 부분 수정은 `PATCH`, 전체 교체는 `PUT`을 씁니다. 정책 "설정"처럼 멱등한 upsert는 `PUT`입니다.
- 시간은 요청/응답 모두 ISO-8601 UTC 문자열입니다. 금액은 **문자열로 직렬화**합니다
  (JSON number로 내보내면 프론트에서 float으로 파싱되어 정밀도가 깨집니다).
- 모든 응답에 `x-request-id`를 실어 보냅니다. 요청에 있으면 그대로, 없으면 생성합니다.
- OpenAPI 문서가 frontend와의 계약 원천입니다. 스키마에 description을 붙이고 예시를 유지합니다.

## Configuration

- 설정은 pydantic-settings로 환경변수에서만 읽습니다. 코드에 기본 시크릿을 두지 않습니다.
- 필수 설정(`DATABASE_URL`, `REDIS_URL`, OIDC issuer 또는 Admin JWT 설정 중 최소 하나)은 부팅 시 검증하고, 없으면
  **기동 실패**시킵니다. 조용히 기본값으로 뜨지 않습니다.
- AWS 자격 증명은 코드가 직접 다루지 않고 기본 credential chain에 위임합니다(운영 IRSA / 로컬 프로필).

## Observability

- `GET /healthz` — 프로세스 생존만 확인. 의존성을 건드리지 않습니다.
- `GET /readyz` — DB/Redis 연결을 확인합니다. 실패 시 503.
- 로그는 structlog JSON. 모든 로그에 `request_id`를 바인딩합니다.
- 로그에 VK 원문, 관리자 토큰, 서비스 토큰을 남기지 않습니다. VK는 `key_prefix`만 남깁니다.

## 참조 구현과의 차이 (요약)

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| Redis 쓰기 | 정책 값을 admin-api가 직접 SET | **DEL만** | AGENTS.md 캐시 소유권 원칙. 두 주체가 같은 키를 쓰면 갱신 순서 역전으로 옛 값이 남습니다 |
| 감사 로그 | 비동기 큐 + 배치 flush | 동기 INSERT | 감사 유실 방지. 03 문서의 감사 요구사항이 우선 |
| chat agent | `admin-chat-agent` 연동 라우터 존재 | **구현하지 않음** | 프로젝트 범위 밖 |

### 참조 구현을 그대로 따르는 항목

| 항목 | 내용 |
|---|---|
| 관리자 인증 | OIDC(JWKS) + Admin JWT(`auth.admin_jwt_configs`) + 서비스 토큰(`svc-`) + dev 토큰. 로컬 비밀번호 계정 없음 |
| 마이그레이션 구성 | 앱과 분리된 마이그레이션 컴포넌트(`alembic.ini` + `env.py` + `versions/` + `init/` + 전용 Dockerfile). 위치만 `backend/db/` |

## Related Documents

- [01-data-model.md](01-data-model.md)
- [02-team-and-user-management.md](02-team-and-user-management.md)
- [03-virtual-key-management.md](03-virtual-key-management.md)
- [04-model-catalog.md](04-model-catalog.md)
- [05-budget-management.md](05-budget-management.md)
- [06-rate-limit-management.md](06-rate-limit-management.md)
- [07-implementation-roadmap.md](07-implementation-roadmap.md)
