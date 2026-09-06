# 04. Model Catalog

| 항목 | 값 |
|---|---|
| 대상 | 모델 alias CRUD, 단가 시계열, 허용 모델 정책 |
| 상위 기준 | [ADR-0003](../../docs/adr-0003-client-api-dialects.md), [00](00-admin-api-architecture.md), [01](01-data-model.md) |
| 공유 계약 | alias 해석 규칙, 캐시 키 `policy:model:{alias}` |

## Objective

client는 `model` 필드에 **alias**를 보냅니다. 카탈로그는 alias를 provider 모델로 해석하는 표이자,
비용 계산의 단가 원천이며, 누가 어떤 모델을 쓸 수 있는지의 정책 원천입니다.

alias를 두는 이유는 세 가지입니다. provider 모델 id가 바뀌어도 client를 고치지 않기 위해,
모델별 접근 제어의 부착점이 필요해서, 그리고 비용 집계 축을 provider id가 아닌 사람이 읽는 이름으로
두기 위해서입니다.

## Alias Rules

- `alias`는 소문자, 숫자, `-`, `.`만 허용합니다(정규식 `^[a-z0-9][a-z0-9.-]{1,127}$`).
  client 요청 값이자 캐시 키의 일부이므로 공백·대문자·슬래시를 허용하지 않습니다.
- alias는 **변경할 수 없습니다.** 이름을 바꾸려면 새 alias를 만들고 구 alias를 `INACTIVE`로 내립니다.
  변경을 허용하면 사용량 이력의 `model_alias`가 가리키는 대상이 흔들립니다.
- alias 삭제는 없습니다. `status=INACTIVE`로만 내립니다. 사용량 이력과 단가 이력이 참조합니다.
- `INACTIVE` alias는 gateway가 즉시 거절합니다. 상태 변경 시 캐시를 지웁니다.

## Dialect Exposure

ADR-0003에 따라 gateway는 OpenAI 호환과 Anthropic Messages 두 방언을 노출하고,
**모델 선택은 방언에 묶이지 않습니다.** 그 자유도의 근거 데이터가 `supported_dialects`입니다.

- Claude 계열은 보통 두 방언 모두 지원합니다.
- Claude 외 모델은 `OPENAI_CHAT`만 지원할 수 있습니다. 그런 모델을 `/v1/messages`로 요청하면
  gateway가 명시적으로 거절합니다(조용히 변환하지 않음 — ADR-0003).
- `supported_dialects`가 빈 배열인 alias는 저장할 수 없습니다.

이 컬럼은 카탈로그의 속성이지 방언 구현이 아닙니다. backend는 값을 관리만 하고,
거절 판정은 gateway가 합니다.

## Pricing

단가는 시계열입니다(`model.model_pricings`). 이유:

- 과거 사용량을 **그 시점 단가**로 설명할 수 있어야 합니다. 단가를 덮어쓰면 지난달 리포트가
  오늘 값으로 바뀝니다.
- Bedrock 온디맨드 단가가 조정되면 조정 시점 전후를 나눠 계산해야 합니다.

규칙:

- 단가 행은 **수정하지 않습니다.** 새 단가는 새 행이고, 이전 행의 `effective_until`을 닫습니다.
- 같은 alias의 유효 구간은 겹칠 수 없습니다. DB의 `EXCLUDE` 제약으로 막습니다(01 문서).
- `effective_from`은 과거 시각도 허용합니다. 단, 과거로 소급하면 이미 기록된
  `usage_events.estimated_cost_usd`는 **바뀌지 않습니다**. 이벤트는 기록 시점 단가로 굳고
  `pricing_id`로 어떤 단가를 썼는지 남깁니다. 소급 재계산이 필요하면 별도 재집계 작업으로 다룹니다
  (07의 미결정 항목).
- 단가 미등록 alias는 `ACTIVE`로 만들 수 없습니다. 비용이 0으로 집계되어 관제 목적을 무너뜨립니다.

### 단가 입력 단위

`per_1k_tokens` USD, `NUMERIC(14,8)`입니다. Bedrock 공시 단가가 1k 토큰 기준이고,
백만 토큰 기준으로 바꾸면 표시만 커질 뿐 반올림 문제는 그대로입니다.

비용 계산식(참조용, 집행은 data plane):

```text
cost = (input_tokens        / 1000) * input_price_per_1k
     + (output_tokens       / 1000) * output_price_per_1k
     + (cache_write_tokens  / 1000) * cache_write_price_per_1k
     + (cache_read_tokens   / 1000) * cache_read_price_per_1k
```

모든 항을 `Decimal`로 계산하고 마지막에 6자리로 양자화합니다.

## Allowed Model Resolution

허용 모델은 세 층입니다. **해석 순서를 여기서 못박고, gateway가 같은 규칙을 구현합니다.**

```text
1) 소유자 기본 정책
   user_allowed_models에 행이 있으면  → 그 목록          (팀 정책을 덮어씀)
   행이 0개면                         → team_allowed_models
   team_allowed_models도 0개면        → 카탈로그의 ACTIVE 전체

2) VK 축소
   virtual_key_allowed_models에 행이 있으면 → 1)과 교집합
   행이 0개면                              → 1) 그대로

3) 카탈로그 상태
   INACTIVE alias는 어느 층에 있든 제외
```

핵심은 **"행 0개"의 의미가 층마다 다르다는 점**입니다.

- `user_allowed_models` 0개 = "사용자 예외 없음, 팀 정책 따름" (전체 허용 아님)
- `team_allowed_models` 0개 = "팀 제한 없음, 전체 허용"
- `virtual_key_allowed_models` 0개 = "키 수준 축소 없음"

이 비대칭은 헷갈리기 쉬우므로 API 응답에 `effective_model_aliases`와 `resolved_from`
(`USER` | `TEAM` | `CATALOG`)를 함께 반환해 화면이 근거를 표시하게 합니다.

## API

### 모델 alias

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `POST` | `/models` | ADMIN | alias 등록 (초기 단가 동시 등록 필수) |
| `GET` | `/models` | 인증된 전원 | 목록. `?status=&provider=&dialect=` |
| `GET` | `/models/{alias}` | 인증된 전원 | 단건 + 현재 단가 |
| `PATCH` | `/models/{alias}` | ADMIN | 표시명, provider 모델 id, 리전, 방언, 토큰 상한, 설명 |
| `PATCH` | `/models/{alias}/status` | ADMIN | `ACTIVE` ↔ `INACTIVE` |

### 단가

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `POST` | `/models/{alias}/pricings` | ADMIN | 새 단가 등록 (이전 구간 자동 종료) |
| `GET` | `/models/{alias}/pricings` | ADMIN / TEAM_LEADER | 단가 이력 |

### 허용 모델 정책

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `GET` | `/teams/{team_id}/allowed-models` | ADMIN / 팀장 | 팀 허용 목록 |
| `PUT` | `/teams/{team_id}/allowed-models` | ADMIN | 전체 교체 (빈 배열 = 제한 해제) |
| `GET` | `/users/{user_id}/allowed-models` | ADMIN / 팀장 / 본인 | 사용자 override |
| `PUT` | `/users/{user_id}/allowed-models` | ADMIN | 전체 교체 |
| `DELETE` | `/users/{user_id}/allowed-models` | ADMIN | override 해제(팀 정책으로 복귀) |
| `GET` | `/users/{user_id}/effective-models` | ADMIN / 팀장 / 본인 | 해석 결과 + 근거 |

`PUT`은 **전체 교체**입니다. 부분 추가/삭제 API를 두지 않는 이유는, 화면이 목록을 통째로 보여주고
저장하는 형태이고, 부분 API는 동시 편집 시 의도치 않은 병합을 만들기 때문입니다.

### 예시

```http
POST /api/v1/models
{
  "alias": "claude-sonnet-4",
  "display_name": "Claude Sonnet 4",
  "provider": "BEDROCK",
  "provider_model_id": "apac.anthropic.claude-sonnet-4-v1:0",
  "region": "ap-northeast-2",
  "supported_dialects": ["OPENAI_CHAT", "ANTHROPIC_MESSAGES"],
  "max_input_tokens": 200000,
  "max_output_tokens": 8192,
  "pricing": {
    "input_price_per_1k": "0.00300000",
    "output_price_per_1k": "0.01500000",
    "cache_write_price_per_1k": "0.00375000",
    "cache_read_price_per_1k": "0.00030000",
    "effective_from": "2026-09-01T00:00:00Z",
    "source": "BEDROCK_ONDEMAND"
  }
}
```

## Cache Invalidation

| 변경 | 삭제 키(제안) | 추가 팬아웃 |
|---|---|---|
| alias 생성/수정/상태 변경 | `policy:model:{alias}` | 없음 |
| 단가 등록 | `policy:model:{alias}` | 없음 |
| 팀 허용 모델 변경 | `policy:allowed_models:team:{team_id}` | 그 팀 소속 VK 전부의 `vk:auth:{hash}` |
| 사용자 허용 모델 변경 | `policy:allowed_models:user:{user_id}` | 그 사용자 소유 VK 전부의 `vk:auth:{hash}` |
| VK 허용 모델 변경 | — | 해당 VK의 `vk:auth:{hash}` |

`INACTIVE` 전환은 "차단"이므로 캐시 삭제 실패를 응답에 드러냅니다(폐기와 같은 취급).

## Validation

- `provider_model_id`는 형식 검증만 하고 존재 여부는 확인하지 않습니다. backend는 Bedrock을
  호출하지 않기 때문입니다. 잘못된 id는 첫 호출에서 gateway가 provider 오류로 드러냅니다.
  등록 화면에 "실호출로 검증되지 않음"을 표시합니다.
- 단가는 음수 불가, `input`/`output`은 0 불가(0이면 비용 관제가 성립하지 않음).
  캐시 단가는 0 허용(미지원 모델).
- `effective_from`이 기존 구간과 겹치면 409 `pricing_period_overlap`.

## Background Jobs

| job | 주기 | 내용 |
|---|---|---|
| `check_missing_pricing` | 1시간 | `ACTIVE`인데 현재 유효 단가가 없는 alias 경고 로그 + 운영 화면 배지 |

Bedrock 공시 단가 자동 동기화(참조 구현의 pricing sync)는 **범위 밖**입니다.
가격 API 접근과 매핑 규칙이 별도 과제이고, 잘못 동기화되면 전 팀의 비용 집계가 틀어집니다.
필요해지면 "미리보기 → 관리자 승인 → 적용" 흐름으로 별도 설계합니다(07 미결정).

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| 방언 | `api_format` 단일 값 | `supported_dialects` 배열 | ADR-0003. 한 모델이 두 방언으로 노출될 수 있어야 합니다 |
| 단가 자동 동기화 | AWS 단가 sync preview/apply 구현 | 범위 밖 | 잘못된 자동 갱신의 파급이 큽니다. 수동 등록 + 누락 감지로 시작 |
| 캐시 | 생성 시 `model:{alias}` 선주입 시도 이력 있음 | 무효화만 | AGENTS.md 캐시 소유권. 참조 구현도 캐시 오염 사고 후 invalidate-only로 회귀했습니다 |
| 캐시 단가 | 5분/1시간 캐시 생성 단가 분리 | write/read 2종 | Bedrock 온디맨드 기준선. 필요 시 컬럼 추가 |
| 모델 다운그레이드 정책 | 예산 소진율 기반 자동 다운그레이드 테이블 보유 | 도입하지 않음 | 05 문서 참조. 사용자가 모르는 사이 다른 모델로 바뀌는 동작은 별도 결정이 필요합니다 |
