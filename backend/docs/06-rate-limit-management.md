# 06. Rate Limit Management

| 항목 | 값 |
|---|---|
| 대상 | rate limit 설정 CRUD, 우선순위 해석, 집행 계약 |
| 상위 기준 | [00](00-admin-api-architecture.md), [01](01-data-model.md) |
| 공유 계약 | 해석 우선순위, 카운터 키와 윈도, 429 응답 규약 — **gateway와 합의 필요** |

## Objective

단기 폭주로부터 gateway와 Bedrock 쿼터를 보호합니다. 예산(05)이 **월 단위 총량**을 다룬다면,
rate limit은 **분 단위 속도**를 다룹니다. 둘은 목적이 다르므로 서로를 대체하지 않습니다.

backend는 한도를 정의하고, **집행과 카운팅은 전적으로 gateway가** 합니다.

## Limit Types

| 한도 | 단위 | 목적 |
|---|---|---|
| `rpm_limit` | 분당 요청 수 | 호출 폭주 방어 |
| `tpm_limit` | 분당 토큰 수 | Bedrock 토큰 쿼터 보호 |
| `concurrency_limit` | 동시 진행 요청 수 | 긴 스트리밍 응답의 자원 점유 제한 |

- 세 한도는 독립입니다. 하나라도 걸리면 거절합니다.
- `tpm_limit`은 요청 시점에 출력 토큰을 알 수 없으므로 **입력 토큰 + 예상 출력(max_tokens)** 으로
  선차감하고 응답 후 실제값으로 정산하는 방식을 gateway와 합의합니다. 이 정산 규칙은 gateway 소유입니다.
- 비용 기반 한도(분당 USD)는 두지 않습니다. 비용 상한은 예산의 역할이고, 두 곳에서 비용을
  차감하면 어느 쪽이 막았는지 운영자가 알 수 없습니다.

## Scope and Resolution **[공유 계약]**

scope는 네 가지입니다: `VIRTUAL_KEY`, `USER`, `TEAM`, `GLOBAL`.
각 설정은 선택적으로 `model_alias` 차원을 가집니다(NULL = 그 scope의 모든 모델).

해석 규칙:

```text
1) 적용 후보를 구합니다 (가장 구체적인 것부터)
     VIRTUAL_KEY(model)  →  VIRTUAL_KEY(all)
   → USER(model)         →  USER(all)
   → TEAM(model)         →  TEAM(all)
   → GLOBAL(model)       →  GLOBAL(all)

2) 각 한도(rpm/tpm/concurrency)별로 **가장 구체적인 정의 하나**를 채택합니다.
   값이 NULL인 한도는 "정의되지 않음"이므로 다음 후보로 넘어갑니다.

3) 채택된 한도들은 **모두 동시에 집행**됩니다.
   단, 같은 한도 종류에 대해 여러 층이 겹칠 때 합산하거나 최소값을 취하지 않습니다.
   가장 구체적인 층 하나가 이깁니다.
```

예시:

| 설정 | 결과 |
|---|---|
| TEAM(all) rpm=600, USER(all) rpm=100 | 그 사용자는 rpm 100 |
| TEAM(all) rpm=600, USER(all) tpm=50000 | rpm 600(TEAM) + tpm 50000(USER) 동시 적용 |
| GLOBAL(claude-sonnet-4) rpm=2000, TEAM(all) rpm=600 | rpm 600. 단 GLOBAL은 별도 축으로 추가 집행(아래) |

`GLOBAL`은 예외입니다. **플랫폼 전체의 모델별 상한**이므로 개별 주체 한도와 별개로 항상 함께
검사합니다. 팀 한도가 아무리 낮아도 모든 팀의 합이 Bedrock 쿼터를 넘을 수 있기 때문입니다.

정리하면 집행은 두 축입니다.

```text
(A) 주체 축: VIRTUAL_KEY > USER > TEAM 중 가장 구체적인 정의
(B) 전역 축: GLOBAL 정의 (모델별)
둘 다 통과해야 요청이 진행됩니다.
```

이 규칙은 API 응답의 `effective_limits`에 근거(`resolved_from`)와 함께 반환해
운영자가 화면에서 "왜 이 한도인가"를 확인할 수 있게 합니다.

## Hierarchy Constraint

- 팀장이 설정하는 멤버 한도는 **팀 한도를 넘을 수 없습니다.** 넘으면 409 `limit_exceeds_parent`.
- ADMIN은 이 제약을 받지 않습니다(팀 한도보다 큰 개인 한도를 의도적으로 줄 수 있음).
  단 감사 로그에 남고, 조회 화면에 "상위 초과" 배지를 표시합니다.
- 팀 한도를 낮출 때 이미 그보다 큰 멤버 한도가 있으면 **거절하지 않고 경고**합니다.
  응답에 `conflicting_children`을 담아 운영자가 정리하게 합니다. 연쇄 자동 조정은 하지 않습니다
  (관리자가 의도하지 않은 값 변경을 만들기 때문).

## Setting Semantics

- 한도 설정은 `PUT` upsert입니다. 같은 `(scope, scope_id, model_alias)` 활성 행은 하나뿐입니다.
- 한도를 **해제**하려면 `DELETE`합니다. `null`을 넣어 저장하는 것과 삭제는 의미가 다릅니다.
  - `rpm=null`로 저장 = "이 층에서 rpm은 정의하지 않음" → 상위 층으로 폴백
  - 행 삭제 = "이 층 정의 전체 제거"
- 세 한도가 모두 `null`인 저장은 400 `empty_rate_limit`으로 거절합니다(행 삭제와 구분 불가).
- 값은 양의 정수입니다. `0`은 "전면 차단"을 뜻하게 되므로 허용하지 않습니다.
  차단이 필요하면 VK를 폐기하거나 사용자를 비활성화합니다.

## API

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `PUT` | `/rate-limits/global/{model_alias}` | ADMIN | 전역 모델 한도 |
| `PUT` | `/rate-limits/team/{team_id}` | ADMIN | 팀 한도. `?model_alias=` 선택 |
| `PUT` | `/rate-limits/user/{user_id}` | ADMIN / 팀장(팀 한도 내) | 사용자 한도 |
| `PUT` | `/rate-limits/virtual-key/{key_id}` | ADMIN / 팀장 | VK 한도 |
| `DELETE` | `/rate-limits/{scope}/{scope_id}` | 동상 | 해제. `?model_alias=` |
| `GET` | `/rate-limits` | ADMIN / 팀장 | 설정 목록. `?scope=&scope_id=&model_alias=` |
| `GET` | `/rate-limits/effective` | ADMIN / 팀장 / 본인 | 해석 결과. `?user_id=&virtual_key_id=&model_alias=` |
| `GET` | `/rate-limits/tree` | ADMIN / 팀장 | 팀 → 멤버 트리 + 상속 표시(화면용) |
| `GET` | `/rate-limits/usage` | ADMIN / 팀장 | 실시간 사용률(gateway 카운터 조회, best-effort) |

### 구현 시 확정한 것 (M8)

문서가 규칙만 정하고 형태를 비워 둔 부분입니다. 구현하면서 확정했습니다.

| 항목 | 확정 |
|---|---|
| 상위(parent)의 정의 | **덜 구체적인 주체 축**입니다. `USER` 의 상위는 `TEAM`, `VIRTUAL_KEY` 의 상위는 소유자(`USER`)와 `TEAM`. `TEAM` 소유 VK 는 사람에 귀속되지 않으므로 상위가 `TEAM` 뿐입니다 |
| `GLOBAL` 은 상위가 아님 | 별도 축이라 주체 한도가 `GLOBAL` 보다 커도 모순이 아닙니다. 둘 다 집행됩니다 |
| 합계 불변식 없음 | rate limit 은 **속도**라 하위끼리 더해지지 않습니다. 600 rpm 팀에 400 rpm 멤버가 둘 있어도 위반이 아닙니다 — 예산(월 총량)과 규칙이 다릅니다 |
| 팀 한도 변경 권한 | `TEAM` scope 설정은 **ADMIN 만**입니다. 팀장은 그 안에서 멤버·VK 한도만 다룹니다 |
| `conflicting_children` 범위 | 같은 모델 차원의 직속 하위만 봅니다(`TEAM` → 멤버, `USER` → 그 사용자 소유 VK) |
| `exceeds_parent` | 목록 조회는 행마다 상위를 해석하지 않으므로 **`null` = 계산 안 함**입니다. 배지가 필요한 화면은 `/tree` 나 `/effective` 를 씁니다 |
| 동시 upsert | 대상 단위 트랜잭션 advisory lock. 막는 것은 write skew 가 아니라 **쓰기 충돌**입니다 — 아래 참조 |
| `DELETE` 경로의 GLOBAL | 대상이 없으므로 `scope_id` 자리에 `global` 을 씁니다. 경로 형태를 scope 마다 다르게 두지 않기 위한 자리표시자입니다 |
| 목록 조회의 GLOBAL | 팀장에게도 보여줍니다. 자기 한도가 왜 그런지 설명하려면 전역 축이 보여야 합니다 |
| 조회의 **모델 차원 격리** | `model_alias` 를 주면 그 모델 행과 전체(NULL) 행이, 주지 않으면 **전체 행만** 후보입니다. 다른 모델 설정이 섞이면 그것이 더 구체적이라 해석에서 이겨, 모델 미지정 조회에 엉뚱한 한도가 나옵니다 |
| `effective` 의 (user, key) 조합 | 사용자 축은 **키가 말하는 소유자**로만 정합니다. 호출자가 준 `user_id` 가 실제 소유자와 다르면 400 `subject_mismatch` |
| 목록의 `scope_id` | 권한과 무관하게 **요청한 필터를 그대로 적용**합니다. 권한 밖 대상을 지정하면 빈 목록이 아니라 403 입니다 |

### 동시 쓰기

예산과 **다른 이유로** 직렬화합니다.

예산의 배분은 "합계 ≤ 팀 한도"라는 집계 불변식이 있어, 읽는 행과 쓰는 행이 달라 write skew 가
생깁니다. rate limit 에는 그런 불변식이 없습니다 — 각 하위를 상위와 **개별 비교**할 뿐입니다.

여기서 막는 것은 **upsert 경합**입니다. 설정 행이 아직 없을 때 `SELECT ... FOR UPDATE` 는
잠글 대상이 없으므로, 같은 `(scope, scope_id, model_alias)` 에 대한 두 요청이 동시에 INSERT 하면
부분 unique index `uq_rate_limit_active` 에서 하나가 터집니다. 대상 단위
`pg_advisory_xact_lock` 으로 직렬화하면 뒤의 요청이 UPDATE 경로로 들어옵니다.

`GLOBAL` 은 팀이 없으므로 예약 키(nil UUID)를 잠금 대상으로 씁니다.

### 설정 예시

```http
PUT /api/v1/rate-limits/team/9f2c...?model_alias=claude-sonnet-4
{"rpm_limit": 600, "tpm_limit": 400000, "concurrency_limit": 40}
```

### 조회 대상 지정

`GET /rate-limits/effective` 는 `user_id` 와 `virtual_key_id` 를 받습니다. 둘 다 주는 경우
**키의 실제 소유자가 진실**이고, 호출자가 보낸 `user_id` 는 검증 대상입니다.

호출자가 준 값을 그대로 믿으면 두 가지가 깨집니다.

1. **인가** — 자기 `user_id` 와 남의 `virtual_key_id` 를 섞어 보내면 소유권 검사가 자기
   자신으로 통과해, 같은 팀 일반 사용자가 다른 사람 키의 정책을 읽을 수 있습니다.
2. **정확성** — 실제로 존재하지 않는 (사용자, 키) 조합의 정책 계층을 계산하게 됩니다.
   화면에 나오는 한도가 그 키로 요청했을 때 실제 집행되는 한도와 달라집니다.

`TEAM` 소유 키는 사람에 귀속되지 않으므로 사용자 축이 없고, ADMIN 과 그 팀 팀장만 조회합니다.

### 해석 결과 예시

```json
{
  "subject": {"user_id": "3a1e...", "virtual_key_id": "b71a...", "model_alias": "claude-sonnet-4"},
  "effective_limits": {
    "rpm_limit":         {"value": 100,    "resolved_from": "USER",        "config_id": "..."},
    "tpm_limit":         {"value": 400000, "resolved_from": "TEAM:model",  "config_id": "..."},
    "concurrency_limit": {"value": null,   "resolved_from": null}
  },
  "global_limits": {
    "rpm_limit": {"value": 2000, "resolved_from": "GLOBAL:model", "config_id": "..."}
  }
}
```

### 실시간 사용률

`GET /rate-limits/usage`는 gateway가 유지하는 카운터를 **읽기만** 합니다.

- Redis 오류나 키 부재는 오류가 아닙니다. `{"available": false, "reason": "..."}`로 응답하고
  설정 화면은 정상 동작합니다. 관측 기능이 관리 기능을 막으면 안 됩니다.
- 카운터 키 구조와 윈도 정의는 gateway 소유이므로, 이 엔드포인트는 gateway의 키 규약이
  확정된 뒤에 구현합니다(Phase 4).

**현재 상태(M8)**: 엔드포인트는 있고 **항상 `available: false`** 입니다. gateway 문서가
카운터 키의 최종 형태를 Phase 4 미확정으로 두고 있어(윈도 표기, ElastiCache cluster mode용
해시태그 `{}`) 키를 만들 수 없습니다. 형태를 추측해 구현하면 합의되지 않은 계약을 만들게 됩니다.

엔드포인트를 미리 두는 이유는 이 응답 형태가 **불가용을 정상 상태로 다루도록** 설계돼 있기
때문입니다. 화면은 지금 붙여도 깨지지 않고, 규약이 확정되면
`RateLimitService.usage()` 한 곳에서 카운터를 읽으면 됩니다.

## Enforcement Contract **[공유 계약]**

```text
Redis (gateway 소유)
  policy:ratelimit:{scope}:{scope_id}:{model_alias|*}   ← 설정 캐시. gateway가 채움, backend가 DEL
  rl:{scope}:{scope_id}:{model_alias}:{window}          ← 집행 카운터. backend는 읽기만
```

- 한도 초과 시 gateway는 429를 반환하고 `Retry-After`를 붙입니다. 응답 본문은 각 방언의
  오류 형식으로 변환하되 내부 오류 코드(`rate_limit_exceeded`)와 어느 층에서 걸렸는지를
  구분 가능하게 남깁니다(ADR-0003의 에러 매핑 요구사항).
- 429는 `usage_events`에 기록되지 않습니다(Bedrock 호출이 없었으므로). 거절 통계는 gateway의
  메트릭 영역이며, 관리 화면은 실시간 카운터만 조회합니다. 거절 이력을 영속화할지는 미결정입니다.

## Cache Invalidation

| 변경 | 삭제 키(제안) |
|---|---|
| 특정 모델 한도 설정/해제 | `policy:ratelimit:{scope}:{scope_id}:{model_alias}` |
| 전체 모델 한도(`model_alias=NULL`) 설정/해제 | `policy:ratelimit:{scope}:{scope_id}:*` — **대상 alias 목록을 DB에서 만들어 개별 삭제** |

- 참조 구현은 이 팬아웃을 Redis `SCAN` 패턴 삭제로 처리합니다. 우리는 카탈로그에서
  `ACTIVE` alias 목록을 읽어 키를 만들어 지웁니다. alias 수는 수십 규모라 비용이 낮고,
  키스페이스 스캔과 오삭제 위험이 없습니다.
- `rl:*` 카운터는 **절대 삭제하지 않습니다.** 지우면 진행 중인 윈도가 리셋되어 한도가 뚫립니다.

## Background Jobs

없습니다. rate limit은 상태를 gateway가 들고 있고, backend는 설정만 소유합니다.

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| scope | USER / TEAM / GLOBAL | + `VIRTUAL_KEY` | 팀 공용 키 하나가 팀 전체 한도를 잡아먹는 것을 막아야 합니다 |
| 비용 한도 | `cpm`/`cph`(분/시간당 USD) 보유 | 도입하지 않음 | 비용 상한은 예산(05)의 역할. 두 곳에서 막으면 원인 진단이 어렵습니다 |
| 동시성 | 없음 | `concurrency_limit` 추가 | 스트리밍 응답이 오래 열려 있어 요청 수만으로는 자원 점유를 못 막습니다 |
| Redis 설정 쓰기 | admin-api가 설정 JSON을 직접 SET | DEL만 | AGENTS.md 캐시 소유권 |
| 팬아웃 무효화 | `SCAN` 패턴 삭제 | 카탈로그 기반 정확 삭제 | 키스페이스 스캔 비용, 다른 plane 키 오삭제 위험 |
| 해석 규칙 | USER > TEAM 폴백, GLOBAL은 모델별 별도 | 한도 종류별 폴백 + GLOBAL 별도 축 명시 | 부분 정의(rpm만 설정) 시 동작이 문서에 없으면 구현이 갈립니다 |

## 미결정

- 429 거절 이력의 영속화 여부와 위치(gateway 메트릭 vs 별도 테이블).
- `tpm_limit`의 선차감/정산 규칙 세부. gateway 브랜치에서 확정합니다.
