# gateway 구현 계획

`gateway`(data plane) 구현에 착수하기 전에 확정해 두는 설계 문서 묶음입니다.
client의 API 진입점부터 Bedrock/Mantle 호출까지의 경로를 다섯 개 영역으로 나눠 각각 문서화합니다.

상위 기준선은 [docs/implementation-plan.md](../../docs/implementation-plan.md)와
[AGENTS.md](../../AGENTS.md)이며, **Phase 1에서 확정된 backend의 공유 계약**
([backend/docs/08-shared-contracts.md](../../backend/docs/08-shared-contracts.md))을 전제로 합니다.
참조 구현은 `awsome-ai-gateway`의 `gateway-proxy`이지만 코드를 옮기지 않고 컴포넌트 분리 방식만 참고합니다.

## 문서 목록

| 문서 | 범위 |
|---|---|
| [01-api-entrypoint.md](01-api-entrypoint.md) | client API 진입점 — 두 방언, 내부 표현, 스트리밍, 에러 매핑 |
| [02-virtual-key-auth.md](02-virtual-key-auth.md) | Virtual Key 인증 — 해시 조회, 허용 모델 해석, 캐시 소유권 |
| [03-client-identification.md](03-client-identification.md) | client 식별 — 분류 규칙, 신뢰 경계, 사용처 |
| [04-backend-routing.md](04-backend-routing.md) | 백엔드 라우팅 — 모델 alias 해석, 리전, provider 선택 |
| [05-provider-invocation.md](05-provider-invocation.md) | Bedrock / Mantle 호출 — adapter, 자격 증명, 사용량 추출 |
| [06-contract-response.md](06-contract-response.md) | backend 회신(09 문서)의 Q1~Q5에 대한 gateway 답변 |

## Objective

gateway는 **정책을 소유하지 않고 읽어서 집행만 하는** 프록시입니다. 이 문서 묶음이 확정하려는 것은
다음 네 가지입니다.

1. 요청 하나가 gateway를 지나는 **단일 경로**의 순서와 각 단계의 책임
2. 방언(dialect)이 파싱·직렬화 계층 밖으로 새지 않게 하는 **내부 경계**
3. control plane과 만나는 지점 — **DB 접근 경계**, **Redis 키 규약**, **usage 이벤트 내용**
4. 각 단계의 **실패 정책**(fail-open / fail-closed)을 명시적으로 고정

## Request Pipeline

요청 처리 순서입니다. 인증·집행·사용량 발행은 방언과 무관하게 이 경로 하나만 지납니다
([ADR-0003](../../docs/adr-0003-client-api-dialects.md)).

```text
                    ┌─ ASGI middleware stack (실행 순서) ─────────────────┐
Client ──HTTP──────▶│ RequestContext   request_id 발급, 타이머 시작        │
                    │ ClientIdentify   UA/헤더 → client 태그 (실패 못함)   │
                    │ Auth (VK)        Bearer → AuthContext (fail-closed) │
                    │ [Phase 4] Budget → RateLimit                        │
                    └──────────────────┬──────────────────────────────────┘
                                       ▼
        ┌────────────── router (/v1/messages | /v1/chat/completions) ──────────┐
        │ 1. DialectParse    방언 본문 → NormalizedRequest (미지원 필드는 거절) │
        │ 2. ModelResolve    alias → ModelConfig  (Redis → PostgreSQL)         │
        │ 3. DialectCheck    모델의 supported_dialects 확인                     │
        │ 4. ScopeCheck      허용 모델 3층 해석 결과와 대조                      │
        │ 5. Invoke          provider adapter 호출 (non-stream / stream)       │
        │ 6. Serialize       내부 이벤트 → 방언 응답 / SSE                      │
        │ 7. Finalize        TokenUsage 확정 → usage 이벤트 기록                │
        └──────────────────────────────────────────────────────────────────────┘
                                       ▼
                     Amazon Bedrock (boto3)  |  Bedrock Mantle (HTTPS + bearer)
```

- 1~4단계는 provider를 모르고, 5단계는 방언을 모릅니다. 이 두 방향의 무지가 이 설계의 핵심입니다.
- 7단계는 **provider 호출이 일어난 요청**에 대해 성공·실패·중단을 가리지 않고 항상 실행됩니다.
  4단계 이전에 거절된 요청은 `usage.auth_events`로 따로 갑니다 (아래 usage 계약 참조).

### 미들웨어 구현 형태

모든 미들웨어는 **pure ASGI**(`__call__(scope, receive, send)`)로 작성하고 Starlette
`BaseHTTPMiddleware`를 쓰지 않습니다. `BaseHTTPMiddleware`는 `StreamingResponse`와 조합했을 때
스트림이 끊기는 알려진 문제가 있어, SSE가 기본인 이 서비스에서는 선택지가 아닙니다.

미들웨어는 `scope["state"]` 딕셔너리로 데이터를 주고받고, Redis·세션 팩토리 같은 프로세스 자원은
`scope["app"].state`로 직접 읽습니다. 별도의 state 주입 미들웨어를 두지 않는 이유는 그 방식이
등록 순서에 의존해 조용히 어긋나기 때문입니다 — `scope["app"]`은 Starlette이 미들웨어 진입 전에
채워 줍니다.

**요청 경로에서 DB 세션을 길게 잡지 않습니다.** 각 소비자가 필요한 시점에 short-lived 세션을 열고
즉시 닫습니다. 요청 전 구간 세션을 유지하면 SSE 응답 중 커넥션이 `idle in transaction`으로 묶여
풀이 고갈됩니다.

## Module Layout

```text
gateway/
├── pyproject.toml
├── Dockerfile
├── src/gateway/
│   ├── main.py                 app factory, lifespan, 미들웨어 등록 순서
│   ├── config.py               Settings (pydantic-settings)
│   ├── db.py                   async engine / session factory (gateway_app 역할)
│   ├── redis_client.py         Redis 연결 (타임아웃·재시도 포함)
│   ├── api/
│   │   ├── health.py           /healthz, /readyz
│   │   ├── anthropic.py        /v1/messages
│   │   └── openai.py           /v1/chat/completions, /v1/models
│   ├── dialects/
│   │   ├── base.py             DialectParser / DialectSerializer 프로토콜
│   │   ├── anthropic.py        ANTHROPIC_MESSAGES 파싱·직렬화·SSE
│   │   └── openai.py           OPENAI_CHAT 파싱·직렬화·SSE
│   ├── core/
│   │   ├── normalized.py       NormalizedRequest / StreamEvent / TokenUsage
│   │   ├── errors.py           내부 오류 코드(C6) + 방언별 매핑
│   │   └── context.py          RequestContext, AuthContext
│   ├── middleware/
│   │   ├── request_context.py
│   │   ├── client_id.py
│   │   └── auth.py
│   ├── services/
│   │   ├── auth_service.py     VK 해석 + 허용 모델 3층 해석 + 캐시
│   │   ├── client_identifier.py
│   │   ├── model_resolver.py   alias → ModelConfig
│   │   ├── usage_recorder.py   usage_events INSERT + 스풀
│   │   └── auth_event_recorder.py  auth_events INSERT
│   ├── providers/
│   │   ├── base.py             ProviderAdapter ABC
│   │   ├── registry.py
│   │   ├── bedrock.py          boto3 InvokeModel
│   │   ├── mantle.py           httpx + bearer
│   │   └── credentials.py      bearer 발급 broker
│   └── schema/                 backend 스키마의 SQLAlchemy 매핑 (읽기 + 허용된 쓰기)
└── tests/
```

`src/gateway/schema/`는 backend가 소유한 테이블을 매핑합니다. gateway는 Alembic 마이그레이션을
두지 않습니다. 스키마 drift는 CI에서 실제 DB에 대해 쿼리를 시도하는 계약 테스트로 잡습니다.

## Shared Contracts

계약의 원본은 [backend/docs/08-shared-contracts.md](../../backend/docs/08-shared-contracts.md)와
[backend/docs/01-data-model.md](../../backend/docs/01-data-model.md)입니다. 여기서는 gateway가
실제로 무엇을 읽고 쓰는지만 정리합니다.

> 위 두 링크는 `feat/admin-backend`가 `main`에 통합된 뒤 해석됩니다. 이 브랜치의 worktree에는
> 아직 `backend/docs/`가 없습니다.

### DB 접근 경계 (역할: `gateway_app`)

| 스키마 | gateway 권한 | gateway가 쓰는 곳 |
|---|---|---|
| `auth` | SELECT + `virtual_keys.last_used_at` UPDATE | VK 인증, 소유자 확인 |
| `model` | SELECT | alias·단가·허용 모델·rate limit 설정 조회 |
| `budget` | SELECT + `budget_usages` UPSERT | 예산 조회·차감 (Phase 4) |
| `usage` | `usage_events` INSERT / SELECT | 사용량 기록 |
| `audit` | **접근 없음** | — |

- **Alembic 마이그레이션의 단일 소유자는 backend입니다.** gateway는 같은 스키마를 읽되 정의하지 않습니다.
- `last_used_at`은 매 요청 UPDATE가 아니라 **분 단위 스로틀링**으로 씁니다(쓰기 증폭 방지).

### 요청 경로에서 읽는 컬럼

| 테이블 | 컬럼 |
|---|---|
| `auth.virtual_keys` | `id`, `key_hash`, `owner_type`, `owner_id`, `team_id`, `status`, `expires_at` |
| `auth.virtual_key_allowed_models` | `model_alias` |
| `auth.users` | `id`, `team_id`, `is_active` |
| `auth.teams` | `id`, `is_active` |
| `model.model_aliases` | `alias`, `provider`, `provider_model_id`, `region`, `supported_dialects`, `status`, `max_output_tokens`, `supports_streaming` |
| `model.model_pricings` | `id`, 단가 4종, `effective_from`, `effective_until` |
| `model.team_allowed_models` / `model.user_allowed_models` | `model_alias` |

### Redis 키 규약

키 이름의 소유자는 gateway이지만, backend가 이미 `backend/src/app/core/cache_keys.py`에
구현해 둔 이름을 **그대로 채택**합니다. 이름을 바꿀 이유가 없는데 이미 동작하는 무효화 경로를
깨뜨릴 이유는 더 없습니다. gateway 전용 키만 새로 추가합니다.

**정책 캐시 — gateway가 채우고 backend는 삭제만**

| 키 | 값 | TTL | 소유 |
|---|---|---|---|
| `vk:auth:{key_hash}` | 인증 컨텍스트 JSON | 300s | 양쪽 합의 |
| `policy:model:{alias}` | 모델 해석 + 현재 단가 (`pricing_id` 포함) | 300s | 양쪽 합의 |
| `policy:allowed_models:{scope}:{id}` | 허용 모델 목록 (`scope ∈ {team, user}`) | 300s | 양쪽 합의 |
| `policy:budget:{scope}:{id}` | 예산 설정 (Phase 4) | 300s | 양쪽 합의 |
| `policy:ratelimit:{scope}:{id}:{alias\|*}` | rate limit 설정 (Phase 4) | 300s | 양쪽 합의 |
| `policy:model:list` | 카탈로그의 ACTIVE alias 목록 | 300s | 양쪽 합의 ([06](06-contract-response.md) Q1) |

`policy:model:list`는 `/v1/models` 응답의 재료이면서 동시에 **허용 모델 3층 해석에서 "team 층
0개 → 카탈로그 전체"의 재료**입니다. 그래서 `model_aliases`의 **모든** 변경(생성·수정·상태 전환)에서
backend가 이 키를 지웁니다. 상태 전환만 트리거로 잡으면 `supported_dialects`가 바뀐 모델이
목록에 옛 값으로 남습니다.

**gateway 전용 — backend는 존재를 알되 건드리지 않음**

| 키 | 값 | TTL |
|---|---|---|
| `vk:miss:{key_hash}` | `1` (음성 캐시). 미등록 키의 DB 재조회 억제 | 30s |

**집행 카운터 — gateway 전용. backend는 읽기만**

| 키 | 용도 |
|---|---|
| `budget:usage:{scope}:{scope_id}:{period}` | 월 소진 누적액 |
| `rl:{scope}:{scope_id}:{model_alias}:{window}` | rate limit 윈도 카운터 |

- 모든 정책 캐시에 **TTL 상한**을 둡니다. 무효화 실패의 영향이 "영구 불일치"가 아니라
  "TTL만큼의 반영 지연"에 머물러야 한다는 backend의 요구사항을 이 값이 충족합니다.
- 키 해시(`key_hash`)는 VK 원문의 SHA-256 hex입니다. **원문은 로그·캐시·메트릭 어디에도 남기지 않습니다.**
- 캐시 miss는 정상 경로입니다. Redis가 없어도 DB로 내려가 동작해야 하며, DB도 없으면 그때 거절합니다.
- **미해결 항목**: ElastiCache cluster mode에서 multi-key Lua는 같은 슬롯을 요구합니다. 위 정책 캐시는
  전부 단일 키 연산이라 문제가 없지만, Phase 4의 집행 카운터는 엔터티 id를 `{}`로 감싸야 할 수
  있습니다(`rl:user:{...}:...`). 카운터 키의 최종 형태는 Phase 4에서 확정하며, 그때 backend의
  `cache_keys.rate_limit_counter()`와 함께 갱신합니다.

### usage 기록

**결정: gateway가 `usage.usage_events`에 직접 INSERT합니다.** 응답을 반환한 뒤 백그라운드 태스크로
쓰고, 실패하면 메모리 스풀에 넣어 재시도합니다. Redis Stream + 별도 worker는 채택하지 않았습니다 —
컴포넌트가 하나 늘고 소유자가 불분명해지는 대가에 비해 얻는 것이 크지 않습니다.
([implementation-plan.md](../../docs/implementation-plan.md)의 Open Decision "비용 기록 경로" 종결)

```text
finalize (응답 반환 직전)        cost 계산, TokenUsage 확정, 메트릭 기록
    │
    └─▶ background task          usage_events INSERT (request_id UNIQUE로 멱등)
              │ 실패
              └─▶ 메모리 스풀 → 주기적 재시도 → 한도 초과 시 드롭 + 카운터 증가
```

- `request_id`가 UNIQUE이므로 재시도가 중복 행을 만들지 않습니다. INSERT는
  `ON CONFLICT (request_id) DO NOTHING`으로 씁니다.
- 스풀은 유실 가능한 버퍼입니다. 드롭은 반드시 메트릭으로 드러냅니다. 조용한 유실이
  비용 관제에서 가장 나쁜 실패 형태입니다.
- 기록 실패가 client 응답에 영향을 주지 않습니다. 이미 응답은 나갔습니다.
- 스풀이 한도를 넘겨 드롭하면 **그 기간의 비용이 과소 집계**됩니다. DB가 복구된 시점에
  사건 단위로 그 사실을 남깁니다 — 형태는 Phase 4에서 확정합니다 ([06](06-contract-response.md) Q5).

**`usage.usage_events`에 채우는 값** (컬럼은 backend 소유)

| 컬럼 | gateway가 넣는 값 |
|---|---|
| `request_id` | 요청 진입 시 발급한 UUID |
| `occurred_at` | 요청 완료 시각 (UTC) |
| `team_id` / `virtual_key_id` | `AuthContext` (팀은 VK의 비정규화 컬럼이라 항상 존재) |
| `user_id` | `owner_type=USER`일 때만. `TEAM` 소유 VK는 NULL |
| `model_alias` / `provider_model_id` | 해석된 `ModelConfig` |
| `dialect` | `OPENAI_CHAT` \| `ANTHROPIC_MESSAGES` |
| `status` | `SUCCESS` \| `ERROR` \| `TIMEOUT` |
| 토큰 4종 | provider 응답값 우선 |
| `estimated_usage` | provider가 usage를 주지 않아 역산한 경우 `true` |
| `latency_ms` / `ttft_ms` / `is_streaming` | 요청 계측값 |
| `estimated_cost_usd` / `pricing_id` | 기록 시점 단가로 계산하고, 쓴 단가 행을 남김 |
| `error_code` | 실패 시 내부 오류 코드(C6) |
| `client` | **추가 요청 중** — 아래 스키마 변경 요청 참조 |

**정책 거절은 `usage.auth_events`로 갑니다.** provider 호출이 없었으므로 비용도 토큰도 없고,
집계 테이블에 0 행을 대량으로 만들면 대시보드 쿼리가 전부 이를 걸러내야 합니다.

## backend에 요청하는 스키마 변경

Phase 1 종료 시점 스키마에는 없지만 gateway 구현에 필요한 항목입니다. **공유 계약 변경**이므로
backend 브랜치와 합의한 뒤 backend의 마이그레이션으로 반영합니다.

| # | 변경 | 이유 | 영향 |
|---|---|---|---|
| S1 | `model.provider` enum에 `BEDROCK_MANTLE` 값 추가 | Mantle은 전송 방식과 IAM 네임스페이스가 다른 별도 백엔드 ([05](05-provider-invocation.md)) | enum 값 추가 |
| S2 | `model.model_aliases.endpoint_url` (text NULL) 추가 | Mantle 엔드포인트는 모델별 속성. 카탈로그 밖에 두면 운영자가 콘솔에서 볼 수 없음 | 컬럼 추가 |
| S3 | `usage.usage_events.client` (text NULL) 추가 | 도구별 사용량 분해 ([03](03-client-identification.md)) | 컬럼 추가 |
| S4 | `usage.auth_events` 테이블 신설 | VK 문서의 "성공/실패 인증 이벤트" 감사 요구 | 테이블 추가 |

### S4 — `usage.auth_events` 제안 형태

```text
id              uuid PK
occurred_at     timestamptz NOT NULL
outcome         text NOT NULL     -- INVALID_KEY | REVOKED | EXPIRED | OWNER_INACTIVE
                                  -- | MODEL_NOT_ALLOWED | MODEL_INACTIVE
                                  -- | BUDGET_EXCEEDED | RATE_LIMITED
virtual_key_id  uuid NULL         -- 키가 식별된 경우에만
key_hash_prefix char(8) NULL      -- 미등록 키를 묶어 보기 위한 값
team_id         uuid NULL
user_id         uuid NULL
client          text NULL
model_alias     text NULL         -- 모델 단계에서 거절된 경우
source_ip       inet NULL
request_id      text NOT NULL
```

- 인덱스: `(occurred_at)`, `(virtual_key_id, occurred_at)`, `(key_hash_prefix, occurred_at)`.
- gateway는 INSERT만 하고 backend가 조회 API를 제공합니다(`gateway_app`에 INSERT GRANT 필요).
- **키 원문이나 전체 해시를 싣지 않습니다.** 앞 8자는 "같은 키가 반복 실패"를 묶기에 충분하고,
  유출돼도 원문 복원에 쓸 수 없습니다.
- 동일 출처의 연속 실패는 gateway에서 임계까지 집계한 뒤 한 번만 기록합니다. 실패마다 INSERT하면
  공격 트래픽이 그대로 DB 부하가 됩니다.

## backend 계약 합의 결과

[08-shared-contracts.md](../../backend/docs/08-shared-contracts.md)의 합의 체크리스트에 대한
gateway 브랜치의 응답입니다.

| 항목 | 결론 |
|---|---|
| C1 키 포맷과 `key_hash` 산출식 | **수용.** `vk_<env>_<base62(32B)>`, `sha256(raw.encode("utf-8")).hexdigest()` |
| C1 인증 통과 조건과 상태 전이 | **수용.** `status ∈ {ACTIVE, ROTATED}` + `expires_at` + 소유자 `is_active` |
| C2 캐시 키 이름 | **수용.** `policy:*` 네임스페이스 채택. gateway 전용 키 2종 추가 통보 |
| C2 TTL 상한 | **확정.** 정책 캐시 300s(`policy:model:list` 포함), `vk:miss` 30s |
| C2 집행 카운터 키 이름 | **조건부 수용.** Phase 4에서 cluster mode hash tag 필요 여부 확정 |
| C3 허용 모델 3층 해석 | **수용.** backend의 `policy/allowed_models.resolve()`와 동일 규칙 구현 |
| C3 예산 / rate limit 해석 | **수용** (집행은 Phase 4) |
| C4 DB 역할과 권한 범위 | **수용.** S4 반영 시 `usage.auth_events` INSERT GRANT 추가 필요 |
| C5 usage 이벤트 컬럼 | **수용 + S3.** 기록 경로는 gateway 직접 INSERT로 확정 |
| C5 429를 기록하지 않음 | **확장 수용.** 401/403/429 전부 `usage_events` 제외, `auth_events`로 (S4) |
| C6 내부 오류 코드 | **수용.** [01](01-api-entrypoint.md)의 방언별 매핑표에 반영 |

## Build Order

| 단계 | 내용 | 산출물 |
|---|---|---|
| ~~M1~~ | 골격 — app factory, 설정, Redis/DB 연결, `/healthz`·`/readyz`, pure ASGI 미들웨어 뼈대 | 기동되는 빈 gateway |
| M2 | VK 인증 + 허용 모델 3층 해석 + client 식별 ([02](02-virtual-key-auth.md), [03](03-client-identification.md)) | 인증된 요청이 라우터까지 도달 |
| M3 | 모델 해석 ([04](04-backend-routing.md)) | `ModelConfig`·`BackendDecision` 확정 |
| M4 | Bedrock 호출 + Anthropic Messages 방언 (non-stream → stream) ([01](01-api-entrypoint.md), [05](05-provider-invocation.md)) | 실제 추론 응답 |
| M5 | OpenAI 호환 방언 + usage/auth 이벤트 기록 | 두 방언 + 관측 완성 |
| M6 | Mantle adapter (S1·S2 반영 후) | 두 백엔드 완성 |

방언은 순차적으로 붙입니다. 내부 표현과 adapter 경계를 먼저 세우는 순서를 지킵니다
([ADR-0003](../../docs/adr-0003-client-api-dialects.md) Follow-up).
M6은 backend의 스키마 변경(S1·S2)에 의존하므로 마지막에 둡니다.

> **현황(2026-09-06)**: M1~M6 구현 완료. 남은 것은 실제 PostgreSQL·Redis·Bedrock을 붙인
> 통합 테스트와 Phase 4입니다. 진행 상태는 [gateway/README.md](../README.md)에 있습니다.

Phase 4(예산·rate limit 집행, 집계)는 이 문서 묶음의 범위 밖이지만, 미들웨어 자리와 Redis 키
네임스페이스는 지금 비워 둡니다.

## Failure Policy

각 단계가 의존하는 저장소가 죽었을 때의 동작을 미리 고정합니다. 나중에 상황을 보고 정하면
경로마다 달라집니다.

| 단계 | Redis 장애 | DB 장애 | 둘 다 장애 |
|---|---|---|---|
| VK 인증 | DB로 우회 | 캐시 hit만 통과, miss는 503 | **거절 (503)** |
| 허용 모델 해석 | DB로 우회 | 캐시 hit만 통과, miss는 503 | **거절 (503)** |
| client 식별 | 영향 없음 | 영향 없음 | 영향 없음 (`other`) |
| 모델 해석 | DB로 우회 | 캐시 hit만 통과 | 거절 (503) |
| usage 기록 | 영향 없음 | 메모리 스풀 후 재시도 | 스풀 한도까지 보관 |

- 인증·허용 모델·모델 해석은 **fail-closed**입니다. 확인 못 한 키와 모델을 통과시키지 않습니다.
  다만 "확인해 보니 무효"(401/404)와 "확인할 수 없음"(503)을 구분합니다. 의존성 장애를 401로
  답하면 client는 멀쩡한 키를 로테이션합니다.
- client 식별은 **fail-open**입니다. 실패해도 `other`로 떨어질 뿐입니다.
  이 비대칭은 의도된 것입니다 — 앞의 셋은 보안·과금 게이트이고, 뒤는 관측 라벨입니다.

## Non-Goals

- 예산·rate limit 집행, 사용량 집계, 대시보드 — Phase 4
- **client별 routing profile** — backend에 `routing_profiles` 테이블이 없고, 리전은
  `model_aliases.region`이 이미 갖고 있습니다. client별 백엔드·계정·기본 모델 강제를 요구하는
  사례가 아직 없어 만들지 않습니다. 상세는 [04](04-backend-routing.md).
- **VK별 `allowed_clients` 게이팅** — 근거 컬럼이 스키마에 없습니다. 상세는 [03](03-client-identification.md).
- cross-account 호출 — role ARN을 둘 자리가 스키마에 없습니다. 필요해지면 ADR로 다룹니다.
- 모델 비교 실험 환경(playground)
- 비 Bedrock provider 확장 — adapter 추상화만 유지하고 구현하지 않음
- 서버사이드 web search, 모델 자동 강등(downgrade), 가용성 fallback 체인 —
  참조 구현에는 있으나 이번 범위에서 제외. adapter/router 경계가 나중에 이들을 받을 수 있게만 둡니다.
