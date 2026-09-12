# 08. 예산·rate limit 집행 (Phase 4)

## Objective

> backend 링크(`../../backend/docs/`)는 `feat/admin-backend`가 `main`에 통합된 뒤 해석됩니다.
> 이 문서가 전제하는 backend M6(예산)·M8(rate limit)은 그 브랜치에 구현돼 있고 아직 전파
> 전입니다. 링크가 깨져 있는 것은 정상 상태입니다([worktree-integration.md](../../docs/worktree-integration.md)).

backend가 소유한 정책을 gateway가 **읽어서 집행**합니다. 예산([backend 05](../../backend/docs/05-budget-management.md))은
월 단위 총량을, rate limit([backend 06](../../backend/docs/06-rate-limit-management.md))은 분 단위
속도를 다룹니다. 둘은 목적이 달라 서로를 대체하지 않고, 같은 자리에서 순서대로 집행됩니다.

이 문서가 확정하는 것은 넷입니다.

1. 집행이 **파이프라인의 어느 단계**에 놓이는가 — 예약해 둔 미들웨어 자리가 왜 틀렸는가
2. **집행 카운터 키의 최종 형태** — backend의 `GET /rate-limits/usage`를 막고 있던 항목
3. `tpm_limit`의 **선차감·정산 규칙** — backend 06 문서가 gateway 소유로 남긴 항목
4. 각 한도의 **실패 정책** — 인증과 왜 다른가

## 집행 위치 — 미들웨어가 아니다

[README](README.md)의 파이프라인은 `Auth → [Phase 4] Budget → RateLimit → router` 로 미들웨어
자리를 비워 뒀습니다. **그 자리는 틀렸습니다.** 구현하면서 드러난 이유는 셋입니다.

| 필요한 것 | 어디서 오는가 | 미들웨어에서 가능한가 |
|---|---|---|
| `model_alias` — rate limit 설정의 차원 | DialectParse + ModelResolve | ✗ 본문을 파싱해야 압니다 |
| `max_tokens` — tpm 선차감의 재료 | DialectParse | ✗ 같은 이유 |
| 동시성 슬롯의 반납 | provider 호출과 스트림의 수명 | ✗ 미들웨어는 스트림이 끝나는 지점을 모릅니다 |

미들웨어에서 본문을 읽으면 `receive` 를 소비해 라우터가 다시 읽지 못하고, 우회하려면 본문을
버퍼링해 두 번 파싱하게 됩니다. SSE가 기본인 서비스에서 요청 본문을 미들웨어가 붙잡는 구조는
그 자체로 위험합니다.

**집행은 라우터 파이프라인의 단계입니다.** `ScopeCheck` 다음, `Invoke` 이전입니다.

```text
1. DialectParse    방언 본문 → NormalizedRequest
2. ModelResolve    alias → ModelConfig
3. DialectCheck    supported_dialects 확인
4. ScopeCheck      허용 모델 3층 해석과 대조
4a. Budget         예산 조회 → 초과 판정          ← 읽기만 함
4b. RateLimit      rpm → tpm → concurrency        ← 카운터를 증가시킴
5. Invoke          provider adapter 호출
6. Serialize       내부 이벤트 → 방언 응답 / SSE
7. Finalize        TokenUsage 확정 → usage 이벤트 + 예산 누적 + tpm 정산 + 슬롯 반납
```

**4a가 4b보다 먼저인 이유**는 예산이 읽기 전용이고 rate limit은 카운터를 증가시키기
때문입니다. 순서를 뒤집으면 어차피 예산으로 막힐 요청이 rate limit 윈도를 소모합니다.
한도를 쓰지 않고 거절할 수 있으면 그렇게 합니다.

**4b 안의 순서**(rpm → tpm → concurrency)도 같은 원리입니다. 싼 것, 가장 흔히 걸리는 것,
되돌릴 필요가 없는 것부터 봅니다.

## 예산 집행

### 해석 [공유 계약]

backend 05의 판정 순서를 그대로 구현합니다.

```text
1) 사용자 예산이 설정돼 있으면 → 사용자 소진 ≥ 사용자 한도 → 정책 적용
2) 팀 예산이 설정돼 있으면     → 팀 소진   ≥ 팀 한도       → 정책 적용
3) 둘 다 미설정                 → 통과
```

- 두 예산을 **동시에** 봅니다. 사용자 예산이 남아도 팀 예산이 소진되면 차단입니다.
  하위가 상위를 우회할 수 없어야 합니다.
- `TEAM` 소유 VK 는 `user_id` 가 없으므로 팀 예산만 봅니다.
- 미설정은 **무제한**입니다. "미설정이면 차단"은 도입 시 전 팀을 멈추고, 설정 누락 사고와
  의도적 무제한을 구분할 수 없게 만듭니다.

| policy | gateway 동작 |
|---|---|
| `HARD_BLOCK` | 429 `budget_exceeded`, `auth_events`에 `BUDGET_EXCEEDED` |
| `SOFT_WARN` | 통과. 로그에 초과 사실을 남기고 요청은 진행 |

### Retry-After 를 붙이지 않습니다

rate limit 429에는 `Retry-After` 를 붙이지만 **예산 429에는 붙이지 않습니다.** 월 예산 초과는
전환 시점이 최대 31일 뒤이고, 그 값을 그대로 주면 SDK 가 그만큼 잠들거나 무의미한 재시도를
반복합니다. 예산 초과는 기다려서 풀리는 상태가 아니라 **사람이 한도를 올려야 풀리는 상태**라,
"언제 다시 오라"는 답이 존재하지 않는 쪽이 정직합니다.

두 429를 client 가 구분할 수 있어야 하므로 내부 코드는 끝까지 분리해 나갑니다
(`budget_exceeded` / `rate_limit_exceeded`).

### 소진 누적 (쓰기 경로)

```text
Finalize (비용 계산 직후)
   ├─▶ Redis  INCRBYFLOAT budget:usage:{scope}:{scope_id}:{period}   팀 + (있으면) 사용자
   └─▶ DB     budget.budget_usages UPSERT (used_usd = used_usd + cost)
```

- 금액 문자열에 **지수 표기를 쓰지 않습니다**(`format(v, "f")`). `INCRBYFLOAT` 가 `1E+2` 를
  파싱하지 못합니다. backend 05가 재시드 경로에서 같은 제약을 지키고 있습니다.
- `budget_usages.limit_usd` 는 NOT NULL 이라 UPSERT 의 INSERT 경로에 값이 필요합니다.
  **4a에서 해석한 한도를 그대로 씁니다** — 집행이 본 값과 스냅샷이 같아야 합니다.
  예산 미설정이면 0 을 넣습니다. 조회 API 는 현재 설정의 한도로 소진율을 계산하므로
  (backend 05) 이 0 이 화면의 소진율을 왜곡하지 않습니다.
- 누적은 **응답을 반환한 뒤 백그라운드**로 씁니다. 사용량 기록과 같은 배경 태스크를 타고,
  실패해도 client 응답에 영향을 주지 않습니다.
- 비용이 0 이면 두 경로 모두 건너뜁니다. 단가 미등록 모델이 카운터에 0 을 계속 더하는 것은
  낭비이고, `budget_usages` 에 의미 없는 행을 만듭니다.

## rate limit 집행

### 두 축 [공유 계약]

backend 06의 해석을 그대로 구현합니다.

```text
(A) 주체 축: VIRTUAL_KEY(model) > VIRTUAL_KEY(*) > USER(model) > USER(*) > TEAM(model) > TEAM(*)
(B) 전역 축: GLOBAL(model) > GLOBAL(*)
둘 다 통과해야 요청이 진행됩니다.
```

- 한도 종류(rpm/tpm/concurrency)**마다 따로** 가장 구체적인 정의 하나를 채택합니다.
  `NULL` 은 "정의되지 않음"이라 다음 후보로 넘어갑니다.
- 겹치는 층을 합산하거나 최소값을 취하지 않습니다. 가장 구체적인 층 하나가 이깁니다.
- `TEAM` 소유 VK 는 `USER` 층을 건너뜁니다.

**한 요청에서 rpm 은 USER 층, tpm 은 TEAM 층이 이길 수 있습니다.** 그때 두 한도는 서로 다른
카운터를 씁니다 — 카운터는 **이긴 설정의 scope 를 따라갑니다.** rpm 한도가 사용자 것인데
팀 단위로 세면 그 한도는 설정한 의미와 다른 것을 재게 됩니다.

### 카운터 키 [공유 계약 — 확정]

> backend 06의 `GET /rate-limits/usage` 가 이 규약을 기다리며 `available: false` 로 막혀
> 있었습니다. 아래로 확정합니다. backend 의 `cache_keys.rate_limit_counter()` 는 **시그니처
> 변경 없이** 그대로 씁니다.

```text
rl:{scope}:{scope_id}:{model_alias}:{window}
```

| 자리 | 값 |
|---|---|
| `scope` | `virtual_key` \| `user` \| `team` \| `global` — **이긴 설정의 scope**(소문자) |
| `scope_id` | 그 scope 의 id. `GLOBAL` 은 `global` |
| `model_alias` | 이긴 설정의 alias. 전체 모델 설정(`NULL`)이면 `*` |
| `window` | `rpm:{epoch_minute}` \| `tpm:{epoch_minute}` \| `conc` |

- `epoch_minute = floor(unix_seconds / 60)` 입니다. **고정 윈도**이고 슬라이딩이 아닙니다.
  경계에서 최대 2배 폭주가 가능하다는 것이 고정 윈도의 알려진 성질인데, 슬라이딩 윈도는
  키마다 정렬 집합과 정리 비용이 붙습니다. 상위에 Bedrock 자체 쿼터라는 백스톱이 있으므로
  경계 2배를 감수하고 단순한 쪽을 택합니다.
- `window` 가 한도 종류를 함께 담는 이유는 **rpm 과 tpm 이 같은 분에 같은 키를 쓰면 안 되기**
  때문입니다. 자리를 하나 더 늘리는 대신 이 자리에 접두사를 둬 backend 의 4인자 헬퍼를
  그대로 유지합니다.
- rpm/tpm 키의 TTL 은 **120초**입니다. 윈도(60초)의 2배라, backend 가 막 닫힌 윈도를 읽어
  "직전 1분 사용률"을 보여줄 수 있습니다.

### 해시 태그를 쓰지 않습니다 [미해결 항목 종결]

[README](README.md)가 "ElastiCache cluster mode 에서 엔터티 id 를 `{}` 로 감싸야 할 수 있다"고
남겨 둔 항목입니다. **감싸지 않습니다.**

cluster mode 가 같은 슬롯을 요구하는 것은 **multi-key 연산**뿐입니다. 그래서 이 설계는
반대 방향에서 제약을 없앱니다 — **모든 카운터 연산이 정확히 한 키만 건드립니다.**

| 한도 | 연산 | 키 수 |
|---|---|---|
| rpm | `INCR` → `EXPIRE NX` → 비교 | 1 |
| tpm | `GET` → 비교 → `INCRBY` → `EXPIRE NX` | 1 |
| concurrency | `INCR` / `DECR` / `EXPIRE NX` | 1 |
| 예산 소진 | `INCRBYFLOAT` → `EXPIRE NX` | 1 |

`MGET` 도 다중 키 Lua 도 쓰지 않습니다. 그 결과 키 이름이 배포 토폴로지(cluster mode 여부)에
묶이지 않고, 아직 정하지 않은 것(ElastiCache 구성)을 지금 정하지 않아도 됩니다.

대가는 **rpm·tpm·concurrency 검사가 서로 원자적이지 않다**는 점입니다. 세 한도가 동시에
빠듯할 때 아주 짧은 순간 한 쪽이 한두 건 넘칠 수 있습니다. 속도 제한에서 이 정도 오차는
설계상 허용 범위이고, 정확성을 위해 키 이름을 토폴로지에 묶는 것이 더 비쌉니다.

### rpm — 증가 후 비교, 되돌리지 않음

```text
n = INCR rl:{...}:rpm:{minute}
EXPIRE rl:{...}:rpm:{minute} 120 NX
n > limit  →  429
```

거절해도 **되돌리지 않습니다.** rpm 이 제한하는 것은 "우리에게 도달한 요청의 속도"이고,
거절된 요청도 도달한 요청입니다. 차단 중에 계속 두드리면 계속 차단되는 것이 의도된
백프레셔입니다. 되돌리면 한도 근처에서 두드릴수록 통과 확률이 올라갑니다.

### tpm — 검사 후 선차감, 응답 후 정산

`tpm` 은 요청 시점에 출력 토큰을 모릅니다. **선차감 후 정산**합니다.

```text
집행 시점   estimate = ceil(요청 텍스트 길이 / chars_per_token) + max_tokens
            used = GET ...:tpm:{minute}
            used + estimate > limit  →  429 (아무것도 쓰지 않음)
            아니면 INCRBY estimate

Finalize    delta = 실제 총 토큰 − estimate        (음수일 수 있음)
            INCRBY ...:tpm:{minute} delta          (delta 가 0 이면 생략)
```

- rpm 과 달리 **검사를 먼저 하고 통과한 요청만 차감합니다.** 증가 후 비교로 하면 거절된
  큰 요청 하나의 추정치가 윈도에 남아 그 분 전체를 막아버립니다. 되돌리는 방법도 있지만,
  쓰지 않고 거절하는 쪽이 되돌리는 쪽보다 단순하고 실패 지점이 적습니다.
- 정산은 **선차감했을 때만** 합니다. 차감한 키(그 분의 키)에 되돌려야 하므로 집행 시점의
  윈도 키를 그대로 들고 있다가 씁니다. 정산이 분 경계를 넘어가 다음 윈도를 오염시키면
  안 됩니다.
- 스트림이 끊겨도 정산은 일어납니다. `Finalize` 는 정상 종료·예외·client 끊김이 모두
  지나는 자리입니다(기존 `stream_with_finalize` 의 `finally`).
- `chars_per_token` 은 설정값(기본 4)입니다. 정확한 토크나이저를 요청 경로에 두지 않는 이유는
  모델마다 다른 토크나이저를 gateway 가 들고 있어야 하고, 그 비용이 매 요청에 붙기 때문입니다.
  **추정은 정산으로 교정되므로 윈도 안에서만 부정확하고 누적되지 않습니다.**

### concurrency — 슬롯 대여

```text
집행 시점   n = INCR rl:{...}:conc ;  EXPIRE rl:{...}:conc {ttl} NX
            n > limit  →  DECR 후 429       ← 되돌립니다
Finalize    DECR rl:{...}:conc
```

- rpm 과 달리 **거절 시 되돌립니다.** concurrency 는 속도가 아니라 **현재 점유 수**를 재는
  게이지이고, 거절된 요청은 아무것도 점유하지 않습니다. 되돌리지 않으면 게이지가 단조 증가해
  한도가 영구히 막힙니다.
- 반납은 `Finalize` 에서 한 번만 일어나야 합니다. 두 번 반납하면 게이지가 음수로 새고,
  그 뒤로 한도가 사실상 사라집니다. 반납은 **멱등**하게 구현합니다(반납 여부 플래그).
- **TTL 이 누수 방어입니다.** pod 가 스트림 도중 죽으면 `DECR` 이 실행되지 않아 슬롯이
  영원히 남습니다. TTL(기본 `stream_timeout + 60초`)을 두면 유령 슬롯이 그 시간 안에
  사라집니다. `EXPIRE ... NX` 라 진행 중인 요청이 TTL 을 계속 밀어내지 않습니다 —
  밀어내면 바쁜 키일수록 누수가 오래갑니다.
- 정렬 집합(`ZADD`/`ZREMRANGEBYSCORE`)으로 만들면 누수가 구조적으로 없어지지만, 요청마다
  멤버가 쌓이고 pod 간 시계 오차가 정확도에 들어옵니다. 지금은 **TTL 로 자가 치유되는 단순한
  쪽**을 택하고, 유령 슬롯이 실제로 문제가 되면 그때 바꿉니다.

## 실패 정책 — 인증과 다릅니다

| 단계 | Redis 장애 | DB 장애 | 둘 다 장애 |
|---|---|---|---|
| VK 인증 (기존) | DB 우회 | 캐시 hit 만 통과 | **거절 (503)** |
| 예산 집행 | `budget_usages` 로 우회 | Redis 카운터로 계속 | **통과 + 경고** |
| rate limit 집행 | **통과 + 경고** | 영향 없음 (설정 캐시 miss 시 통과) | **통과 + 경고** |

**인증은 fail-closed 이고 집행은 fail-open 입니다.** 이 비대칭은 의도된 것이며 근거는
"막지 못했을 때 무엇을 잃는가"입니다.

- 확인 못 한 **키**를 통과시키면 인가되지 않은 접근이고 손실에 상한이 없습니다.
- 확인 못 한 **예산**을 통과시키면 장애 시간만큼의 초과 지출이고, 그 비용은
  `usage_events` 에 그대로 남아 사후에 정확히 보입니다. 반대로 fail-closed 로 두면
  Redis 순단이 전사 LLM 장애가 됩니다.
- rate limit 은 upstream 용량을 보호하는데, **Bedrock 자체 쿼터라는 백스톱이 이미 있습니다.**
  우리가 못 세는 동안에도 Bedrock 의 `ThrottlingException` 이 429 로 매핑돼 나갑니다
  ([05](05-provider-invocation.md)). 보호막이 두 겹이라 바깥 한 겹이 잠시 없어도 벌거벗지 않습니다.

fail-open 은 **조용하면 안 됩니다.** 우회할 때마다 경고 로그를 남기고, 그 값이 곧 "집행되지
않은 구간"의 규모입니다.

## 정책 캐시

| 키 | 값 | TTL |
|---|---|---|
| `policy:budget:{scope}:{id}` | 예산 설정 또는 **미설정 표식** | 300s |
| `policy:ratelimit:{scope}:{id}:{alias\|*}` | rate limit 설정 또는 **미설정 표식** | 300s |

- **미설정도 캐시합니다.** 예산이 없는 팀이 다수인 초기 운영에서 미설정을 캐시하지 않으면
  거의 모든 요청이 DB 를 봅니다. 음성 캐시가 없는 정책 캐시는 정책이 적은 환경에서
  캐시가 아닙니다.
- backend 는 이 키를 **삭제만** 합니다(AGENTS.md 캐시 소유권). 값을 채우는 주체는 gateway 하나뿐이라
  갱신 역전이 생기지 않습니다.
- 한 요청이 보는 후보는 최대 8개입니다(주체 3층 × 모델 유무 2 + 전역 2). 각 키가 단일 키
  조회라 cluster mode 에서도 문제가 없고, 대부분은 미설정 표식이라 즉시 끝납니다.
- 캐시 miss 는 **한 번의 쿼리로 모아 읽습니다.** miss 마다 쿼리를 날리면 요청 하나가 DB 왕복
  8번이 됩니다.

## 거절 기록

| 거절 | `auth_events.outcome` | HTTP |
|---|---|---|
| 예산 초과 (`HARD_BLOCK`) | `BUDGET_EXCEEDED` | 429 |
| rpm / tpm / concurrency 초과 | `RATE_LIMITED` | 429 |

- provider 호출이 없었으므로 `usage_events` 에 가지 않습니다(C5 확장 수용).
- 기존 거절 기록과 같은 창(window) 묶음을 지납니다. 한도에 걸린 client 는 보통 즉시
  재시도하므로, 실패마다 INSERT 하면 그 트래픽이 그대로 DB 부하가 됩니다.
- **어느 층에서 걸렸는지**는 로그에 남깁니다(`scope`, `limit_type`, `limit`, `observed`).
  `auth_events` 에 층을 담을 컬럼이 없고, 그 한 가지를 위해 스키마 변경을 요청할 만큼
  조회 요구가 분명하지 않습니다. 필요해지면 S5 로 요청합니다.

## 이번 범위 밖

- **429 거절 이력의 영속화** — backend 06의 미결정 항목입니다. 지금은 로그와 `auth_events`
  까지이고, 별도 테이블은 만들지 않습니다.
- **예산 임계 알림 발송** — `notified_thresholds` 는 backend 의 `check_budget_thresholds` job
  소유입니다. gateway 는 소진액만 올립니다.
- **예산 기반 모델 자동 강등** — [04](04-backend-routing.md)의 제외 항목 그대로입니다.
- **스풀 드롭 시 과소 집계 사건 기록**(docs/06 Q5) — 예산 누적도 같은 배경 경로를 타므로
  드롭되면 소진액이 함께 과소 집계됩니다. 지금은 기존 `usage.record_dropped` 로그가 그
  규모를 드러내고, 전용 사건 테이블은 만들지 않습니다.
