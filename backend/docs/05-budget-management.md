# 05. Budget Management

| 항목 | 값 |
|---|---|
| 대상 | 예산 설정/배분 CRUD, 소진 조회, 집행 계약 |
| 상위 기준 | [docs/usage-and-cost-observability.md](../../docs/usage-and-cost-observability.md), [00](00-admin-api-architecture.md), [01](01-data-model.md) |
| 공유 계약 | 소진 카운터 키, 기간 경계 정의, 차단 판정 규칙 — **gateway와 합의 필요** |

## Objective

팀/사용자 단위로 월 예산을 정하고, 소진 상황을 보여주고, 초과 시 어떻게 할지를 정책으로 남깁니다.
**집행은 gateway가 하고, backend는 정책과 가시성을 소유합니다.**

## Scope

- 팀 예산 설정, 팀 예산의 멤버 배분
- 사용자 예산 설정
- 기간별 소진 조회(팀/사용자/모델 breakdown)
- 초과 정책(`HARD_BLOCK` / `SOFT_WARN`)과 경고 임계값
- 소진값 재시드(운영용)

범위 밖: 자동 모델 다운그레이드, 완전한 chargeback 워크플로
([implementation-plan.md](../../docs/implementation-plan.md) Out of Scope).

## Period Definition **[공유 계약]**

- 기간 단위는 **월(`MONTHLY`)** 하나입니다. `YYYY-MM` 문자열로 표기합니다.
- 기준 시간대는 **UTC**입니다. `2026-09`는 `2026-09-01T00:00:00Z` 이상
  `2026-10-01T00:00:00Z` 미만입니다.
- 사내 사용자는 KST로 보지만, 집계 경계를 로컬 시간으로 두면 gateway의 카운터 키와
  집계 배치와 대시보드가 각자 다른 경계를 쓰게 됩니다. **저장은 UTC, 표시만 KST**로 고정합니다.
  화면에는 "UTC 기준 월"임을 명시합니다.
- 일/주 단위 예산은 두지 않습니다. 단기 폭주 방어는 rate limit(06)의 역할입니다.

## Budget Scope and Resolution

| scope | 대상 | 의미 |
|---|---|---|
| `TEAM` | 팀 | 팀 전체 소비 상한 |
| `USER` | 사용자 | 개인 상한 |

집행 시 판정 순서 **[공유 계약]**:

```text
1) 사용자 예산이 설정되어 있으면 → 사용자 소진 ≥ 사용자 한도  → 정책 적용
2) 팀 예산이 설정되어 있으면     → 팀 소진   ≥ 팀 한도        → 정책 적용
3) 둘 다 미설정                   → 통과 (차단하지 않음)
```

- 두 예산은 **동시에 검사**합니다. 사용자 예산이 남아도 팀 예산이 소진되면 차단됩니다.
  하위가 상위를 우회할 수 없어야 합니다.
- 예산 미설정을 "무제한"으로 해석합니다. "미설정이면 차단"은 초기 도입 시 전 팀을 멈추게 하고,
  운영자가 설정을 빠뜨리는 사고와 의도적 무제한을 구분할 수 없게 만듭니다.
  대신 **예산 미설정 팀 목록**을 운영 화면에 상시 노출합니다.
- VK 단위 예산은 두지 않습니다. VK는 인증 수단이지 비용 주체가 아니며, 축을 늘리면 배분 검증이
  급격히 복잡해집니다. VK별 비용은 조회 축으로만 제공합니다.

## Allocation

팀 예산을 멤버에게 배분합니다. 배분은 **합계 검증이 있는 사용자 예산 일괄 설정**입니다.

```http
PUT /api/v1/budgets/team/{team_id}/allocation
{
  "allocations": [
    {"user_id": "3a1e...", "limit_usd": "40.0000"},
    {"user_id": "77bd...", "limit_usd": "35.0000"}
  ]
}
```

규칙:

- 배분 합계는 팀 한도를 **초과할 수 없습니다.** 초과 시 409 `allocation_exceeds_team_budget`
  (`details`에 합계와 한도를 담습니다).
- 합계가 팀 한도보다 작은 것은 허용합니다(미배분 여유분). 응답에 `unallocated_usd`를 반환합니다.
- 배분 대상은 그 팀 소속 활성 사용자여야 합니다. 아니면 400.
- 팀장은 자기 팀 배분만 할 수 있고, 팀 한도 자체는 바꿀 수 없습니다(00 문서 인가 표).
- 배분은 원자적입니다. 하나라도 검증에 실패하면 전체를 롤백합니다.

## Over-budget Policy

| policy | 의미 | gateway 동작 |
|---|---|---|
| `HARD_BLOCK` | 초과 시 차단 | 429 + `budget_exceeded` 오류 (각 방언 형식으로 변환) |
| `SOFT_WARN` | 초과해도 통과, 경고만 | 요청 통과, 경고 이벤트 기록 |

- 기본값은 `HARD_BLOCK`입니다. 비용 관제가 목적인 플랫폼에서 기본이 통과면 상한은 장식입니다.
- `warn_thresholds`(기본 `[80, 90, 100]`)는 %입니다. 임계 도달 시 알림을 보내고
  `budget_usages.notified_thresholds`에 기록해 중복 발송을 막습니다.
- 알림 채널 연동은 Phase 4 이후입니다. 지금은 임계 도달 사실을 기록하고 조회 API로 노출합니다.
- `THROTTLE`(초과 시 속도 저하) 정책은 두지 않습니다. 참조 구현에는 있지만, 지연으로 나타나는
  차단은 client가 원인을 알 수 없어 장애로 오인됩니다. 차단하려면 차단하고 이유를 말합니다.

## Enforcement Contract **[공유 계약]**

> 카운터 키와 판정 위치는 gateway가 소유합니다. 아래는 합의 대상 제안입니다.

```text
Redis (요청 경로, gateway 소유)
  budget:usage:{scope}:{scope_id}:{period}   ← 소진 누적액. gateway가 INCRBYFLOAT
  policy:budget:{scope}:{scope_id}           ← 예산 설정 캐시. gateway가 채움, backend가 DEL

PostgreSQL (내구 사본)
  budget.budget_usages                        ← 사용량 기록 경로가 UPSERT
  budget.budget_configs                       ← backend가 소유하는 설정 원천
```

역할 분담:

- **backend**: `budget_configs` CRUD, `policy:budget:*` 캐시 DEL, 조회 API.
- **gateway / 사용량 기록 경로**: Redis 카운터 증가, `budget.budget_usages` UPSERT.
- backend는 **카운터를 쓰지 않습니다.** 유일한 예외가 아래 재시드입니다.

### 소진값 재시드 (운영 예외)

```http
PUT /api/v1/budgets/usages/reseed
{"items": [{"scope": "TEAM", "scope_id": "9f2c...", "period": "2026-09", "used_usd": "812.4300"}]}
```

- 용도: 데이터 마이그레이션, 장애 후 카운터 소실 복구, 오집계 정정.
- **ADMIN 전용**이고 감사 로그에 before/after를 남깁니다.
- Redis 카운터와 `budget_usages`를 함께 갱신합니다. 한쪽만 고치면 다음 요청에서 되돌아갑니다.
- 이것이 "control plane은 캐시를 채우지 않는다" 원칙의 유일한 예외입니다.
  자동 경로가 아니라 사람이 명시적으로 호출하는 복구 도구이기 때문에 허용합니다.

### Redis와 DB의 불일치

Redis 카운터가 빠르고, `budget_usages`가 내구적입니다. 둘이 어긋날 수 있습니다.

- 조회 API는 **Redis 값을 우선** 표시하고, 없으면 DB 값을 씁니다. 운영자가 보는 숫자는
  집행에 쓰이는 숫자와 같아야 합니다.
- 응답에 `source: "redis" | "db"`를 포함해 어느 쪽을 봤는지 드러냅니다.
- 월 경계 직후 Redis 키가 없는 것은 정상입니다(0에서 시작).
- 주기 job이 DB 기준으로 Redis 값을 검증하고 차이가 임계 이상이면 경고합니다. **자동 교정하지
  않습니다.** 자동 교정은 두 주체가 같은 값을 쓰는 경합을 만듭니다.

## API

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `PUT` | `/budgets/team/{team_id}` | ADMIN | 팀 예산 설정(upsert) |
| `DELETE` | `/budgets/team/{team_id}` | ADMIN | 팀 예산 해제 |
| `PUT` | `/budgets/user/{user_id}` | ADMIN / 팀장(자기 팀, 팀 한도 내) | 사용자 예산 설정 |
| `DELETE` | `/budgets/user/{user_id}` | ADMIN / 팀장 | 사용자 예산 해제 |
| `GET` | `/budgets/team/{team_id}/allocation` | ADMIN / 팀장 | 배분 현황(한도, 배분 합계, 미배분) |
| `PUT` | `/budgets/team/{team_id}/allocation` | ADMIN / 팀장 | 배분 일괄 설정 |
| `GET` | `/budgets/summary` | ADMIN / 팀장(자기 팀) | 기간별 소진 요약. `?period=2026-09&scope=TEAM` |
| `GET` | `/budgets/team/{team_id}/usage` | ADMIN / 팀장 | 팀 소진 상세 + 멤버·모델 breakdown |
| `GET` | `/budgets/user/{user_id}/usage` | ADMIN / 팀장 / 본인 | 사용자 소진 상세 |
| `GET` | `/me/budget` | 인증된 전원 | 내 예산과 소진율 |
| `PUT` | `/budgets/usages/reseed` | ADMIN | 소진값 재시드(운영 예외) |
| `GET` | `/budgets/unset` | ADMIN | 예산 미설정 팀/사용자 목록 |

`GET /budgets/unset` 은 `?team_id=` 로 한 팀의 미설정 멤버만 좁혀 볼 수 있습니다.

### 구현 시 확정한 것 (M6)

문서가 규칙만 정하고 형태를 비워 둔 부분입니다. 구현하면서 확정했습니다.

| 항목 | 확정 |
|---|---|
| 배분의 의미 | **전체 교체.** 목록에 없는 멤버의 기존 배분은 해제됩니다. 부분 갱신이면 합계 검증이 "이번에 보낸 것"만 보게 되어 상한을 넘길 수 있습니다 |
| 팀 예산 없이 배분 | 409 `team_budget_not_set`. 상한이 없으면 검증할 기준이 없습니다 |
| 오류 코드 분리 | 일괄 배분 초과는 `allocation_exceeds_team_budget`, 단건 사용자 예산 설정·팀 한도 인하로 합계가 넘는 경우는 `budget_limit_conflict`(00 문서 예시) |
| 한도 인하 | 이미 배분된 합계보다 낮은 팀 한도는 거절합니다. 허용하면 하위 합이 상위를 넘은 상태가 남습니다 |
| `limit_usd = 0` | **"쓸 수 없음"** 입니다. 무제한이 아닙니다 — 무제한은 설정 해제로 표현합니다 |
| 소진율 분모 0 | 한도 0 에서 소진이 있으면 100%, 없으면 0% |
| `remaining_usd` | 초과분을 음수로 그대로 둡니다. 0 으로 깎으면 `SOFT_WARN` 에서 얼마나 넘겼는지 알 수 없습니다 |
| 단계 판정 | `100% 이상 → EXCEEDED`, `100 미만 임계 중 최고 도달 → CRITICAL`, 그 아래 → `WARNING`, 미달 → `NORMAL` |
| 임계 알림 목록 | 100 은 단계 판정에선 EXCEEDED 에 밀리지만 **알림 목록에는 남습니다.** 초과 시점에도 한 번은 나가야 합니다 |
| 사용자 예산 인가 | 설정은 ADMIN / 팀장(자기 팀). 조회는 ADMIN / 팀장(자기 팀) / 본인. 팀 소속을 봐야 판정되므로 service 에서 확인합니다 |
| 재시드 중복 | 같은 `(scope, scope_id, period)` 가 두 번 오면 400. `budget_usages` 의 PK 라 커밋 시 충돌합니다 |
| 재시드 감사 | **항목마다 한 건**을 남깁니다. 한 건으로 묶으면 `resource_id` 로 대상을 찾을 수 없습니다 |
| 카운터 문자열 | 지수 표기 금지(`format(v, "f")`). gateway 의 `INCRBYFLOAT` 가 `1E+2` 를 파싱하지 못합니다 |

### 요약 응답 예시

```json
{
  "period": "2026-09",
  "source": "redis",
  "items": [
    {
      "scope": "TEAM",
      "scope_id": "9f2c...",
      "name": "search-platform",
      "limit_usd": "1000.0000",
      "used_usd": "812.4300",
      "remaining_usd": "187.5700",
      "usage_pct": "81.24",
      "policy": "HARD_BLOCK",
      "alert_level": "WARNING"
    }
  ]
}
```

- 금액은 문자열입니다(00 문서 규약). `usage_pct`도 문자열입니다 — 소진율은 차단 판정의
  근거라서 표시 단계에서 반올림이 달라지면 안 됩니다.
- `alert_level`은 `warn_thresholds` 기준으로 backend가 계산합니다(`NORMAL`/`WARNING`/`CRITICAL`/`EXCEEDED`).
  프론트가 임계값 로직을 중복 구현하지 않게 하기 위해서입니다.
- `source`는 **항목마다** 실립니다. 최상위 `source`는 항목들의 종합이고, 섞여 있으면 `mixed`입니다.
  한쪽으로 뭉뚱그리면 거짓이 됩니다(어떤 항목은 Redis, 어떤 항목은 DB에서 왔을 수 있습니다).
- Redis 장애 시 조회는 실패하지 않고 DB로 떨어집니다. 대신 `source`가 `db`로 드러납니다.

## Setting Change Semantics

- 예산 한도 변경은 **즉시 유효**하며 당월 소진 누적에는 영향을 주지 않습니다.
  한도만 바뀌므로, 이미 초과 상태였다면 한도를 올리는 즉시 다시 통과합니다.
- 기존 설정을 수정할 때는 이전 행을 `is_active=false`로 닫고 새 행을 만듭니다(01 문서).
  "언제 누가 한도를 올렸는가"가 감사에 남아야 합니다.
- `budget_usages.limit_usd`는 **기간 시작 시점 스냅샷**입니다. 기간 중 한도가 바뀌면
  집행은 새 한도를 따르고, 스냅샷은 참고값으로 남습니다. 조회 API는 항상 현재 설정의 한도를
  기준으로 소진율을 계산합니다.

## Cache Invalidation

| 변경 | 삭제 키(제안) |
|---|---|
| 팀 예산 설정/해제 | `policy:budget:team:{team_id}` |
| 사용자 예산 설정/해제 | `policy:budget:user:{user_id}` |
| 배분 일괄 설정 | 배분 대상 사용자 전원의 `policy:budget:user:{user_id}` |

`budget:usage:*` 카운터는 **삭제하지 않습니다.** 지우면 소진액이 0으로 리셋되어 초과 상태가
풀립니다. 설정 캐시와 소진 카운터를 같은 접두사로 두지 않는 이유이기도 합니다.

## Background Jobs

| job | 주기 | 내용 |
|---|---|---|
| `aggregate_usage_daily` | 10분 | `usage.usage_events` → 일 집계 테이블 |
| `aggregate_usage_monthly` | 1시간 | 일 집계 → 월 집계 |
| `check_budget_thresholds` | 10분 | 임계 도달 감지, `notified_thresholds` 갱신 |
| `verify_budget_counters` | 1시간 | Redis vs DB 차이 검증(경고만, 자동 교정 없음) |

집계 작업은 backend가 소유합니다. 원천 이벤트는 gateway가 쓰고 backend가 읽는다는 경계는
유지됩니다(집계 테이블은 backend가 씁니다).

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| Redis 설정 캐시 | admin-api가 예산 설정을 직접 SET | DEL만 | AGENTS.md 캐시 소유권. 두 주체 동시 쓰기의 갱신 역전 방지 |
| 정책 종류 | `HARD_BLOCK`/`SOFT_WARNING`/`THROTTLE` | `HARD_BLOCK`/`SOFT_WARN` | 지연으로 나타나는 차단은 원인 진단이 불가능합니다 |
| 축 | scope + client(앱)별 예산 세분화 | scope만 | client 축은 이 프로젝트의 요구사항이 아닙니다. 필요 시 열 추가로 확장 |
| 자동 다운그레이드 | 소진율 기반 모델 자동 전환 테이블 | 도입하지 않음 | 사용자가 모르는 사이 응답 품질이 바뀝니다. 필요하면 ADR로 별도 결정 |
| 기간 | MONTHLY, 시간대 이슈 회귀 테스트 존재 | MONTHLY + UTC 명시 | 경계를 문서에서 먼저 못박아 같은 사고를 예방 |
| 소진 재시드 | 일반 API로 제공 | ADMIN 전용 + 감사 필수 + 예외임을 명시 | 카운터 쓰기는 원칙의 예외이므로 예외로 취급해야 합니다 |

## 미결정

- `TEAM` 소유 VK의 사용량을 사용자 예산에 어떻게 반영할지(현재는 팀 예산에만 반영).
  `usage.monthly_usage_aggregates`의 `user_id`가 PK라 NULL을 담을 수 없다는 점이 M7에서
  같이 걸립니다(07 문서 미결정 #5).
- 임계 알림 채널(Slack/메일)과 발송 주체. Phase 4에서 결정합니다.
- 과거 단가 소급 변경 시 재집계 정책(04 문서와 연동).
