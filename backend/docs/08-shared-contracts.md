# 08. Shared Contracts (backend ↔ gateway)

| 항목 | 값 |
|---|---|
| 상태 | **합의 완료 (일부 조건부).** gateway 회신과 후속 항목은 [09](09-gateway-contract-response.md) |
| 대상 | 두 plane이 코드를 공유하지 않고 만나는 지점 전부 |
| 상위 기준 | [AGENTS.md](../../AGENTS.md), [docs/implementation-plan.md](../../docs/implementation-plan.md) |

## 이 문서의 목적

`backend/`와 `gateway/`는 HTTP로 통신하지 않습니다. 대신 **DB 스키마와 Redis 키 규약**으로만
만납니다. 규약이 흩어져 있으면 한쪽 변경이 조용히 다른 쪽을 깹니다. 이 문서는 00~07에 흩어진
**[공유 계약]** 표시 항목을 한 장에 모은 것이고, gateway 브랜치가 읽는 단일 입구입니다.

여기 있는 항목은 **backend 단독으로 바꿀 수 없습니다.** 변경은 양쪽 합의 + ADR 대상입니다.

## C1. Virtual Key 인증

### 키 포맷

```text
vk_<env>_<base62(32 bytes)>       env ∈ {live, dev}
표시용 prefix = "vk_" + env + "_" + 랜덤 앞 6자
```

### 조회 키

```python
key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()   # 소문자 hex 64자
```

- `auth.virtual_keys.key_hash`에 이 값이 UNIQUE로 들어갑니다.
- gateway는 요청의 Bearer 토큰으로 같은 식을 계산해 캐시/DB를 조회합니다.
- **해시 알고리즘과 입력 인코딩을 한쪽만 바꾸면 전 키가 인증 실패합니다.**

### 인증 통과 조건

```text
통과 = status ∈ {ACTIVE, ROTATED}
     AND (expires_at IS NULL OR expires_at > now())
     AND 소유자(users/teams)가 is_active
```

`ROTATED`는 유예 기간 동안만 통과합니다. 유예는 backend가 `expires_at`을 당겨 표현하므로,
gateway는 별도 유예 로직 없이 위 조건만 봅니다.

### 상태 전이 (backend가 소유)

| from | to | 트리거 |
|---|---|---|
| — | `ACTIVE` | 발급 |
| `ACTIVE` | `ROTATED` | 로테이션 (`expires_at`을 유예 종료로 단축) |
| `ACTIVE` | `REVOKED` | 폐기 / 사용자 비활성화 / 팀 일괄 폐기 |
| `ACTIVE` | `EXPIRED` | 만료 job |
| `ROTATED` | `REVOKED` | 유예 종료 job |
| `REVOKED`·`EXPIRED` | — | 되돌아가지 않음 |

## C2. Redis 키 규약

> 키 이름의 최종 소유자는 gateway입니다. 아래는 backend가 전제하고 있는 제안입니다.

### 정책 캐시 — gateway가 채우고, backend가 삭제만

TTL은 gateway가 확정했습니다(2026-09-06 회신).

| 키 | 값 | TTL | 채움 |
|---|---|---|---|
| `vk:auth:{key_hash}` | 인증 컨텍스트 JSON (`virtual_key_id`, `owner_type`, `owner_id`, `team_id`, `user_id`, `status`, `expires_at`, `allowed_model_aliases`, `idp_subject`) | 300s | gateway |
| `policy:model:{alias}` | 모델 해석 + 현재 단가 (`pricing_id` 포함) | 300s | gateway |
| `policy:allowed_models:{scope}:{id}` | `scope ∈ {team, user}` | 300s | gateway |
| `policy:budget:{scope}:{id}` | 예산 설정(한도, 정책, 임계값) | 300s | gateway |
| `policy:ratelimit:{scope}:{id}:{model_alias\|*}` | rate limit 설정 | 300s | gateway |

- `allowed_model_aliases`는 3층 해석이 끝난 **최종 목록**입니다. "전체 허용"(`None`)을 캐시에 넣지
  않습니다. 빈 목록은 "이 키로 쓸 수 있는 모델 없음"이라는 유효한 상태입니다.
- `idp_subject`는 C2 원안에 없던 필드입니다. gateway가 provider metadata로 전달합니다
  ([09](09-gateway-contract-response.md) Q4에 확인 대기 항목).

### gateway 전용 캐시 — backend는 존재를 알되 건드리지 않음

| 키 | 값 | TTL |
|---|---|---|
| `vk:miss:{key_hash}` | 미등록 키의 음성 캐시. DB 재조회 억제 | 30s |
| `policy:model:list` | 활성 alias 목록 (`/v1/models` 응답 재료) | 60s |

`policy:model:list`를 낡게 만드는 주체는 backend(카탈로그 변경)입니다. 무효화 주체를 어디에 둘지는
[09](09-gateway-contract-response.md) Q1에서 확인 중입니다.

### 집행 카운터 — gateway 전용. backend는 읽기만

| 키 | 용도 |
|---|---|
| `budget:usage:{scope}:{scope_id}:{period}` | 월 소진 누적액 |
| `rl:{scope}:{scope_id}:{model_alias}:{window}` | rate limit 윈도 카운터 |

- backend는 이 키를 **쓰지도 지우지도 않습니다.** 지우면 소진액이 0으로 리셋되고 윈도가 풀립니다.
- 유일한 예외: `PUT /api/v1/budgets/usages/reseed` (ADMIN 전용, 감사 필수, 05 문서).

### 무효화 규칙

- backend는 **DEL만** 합니다. 값을 채우지 않습니다.
- 순서는 **트랜잭션 커밋 → 캐시 삭제**입니다. 뒤집으면 커밋 전에 gateway가 옛 값을 다시 채웁니다.
- 팬아웃은 `SCAN` 패턴 삭제가 아니라 DB에서 대상 키 목록을 만들어 정확히 삭제합니다.
- 삭제 실패는 `audit.cache_invalidation_failures`에 기록하고 재시도합니다. 요청은 실패시키지 않습니다.
- **gateway 요구사항**: 모든 정책 캐시에 TTL 상한을 둡니다. 무효화 실패의 영향이
  "영구 불일치"가 아니라 "TTL만큼의 반영 지연"에 머물러야 합니다. TTL 값은 gateway가 정합니다.

## C3. 정책 해석 규칙

두 plane이 같은 답을 내야 하는 규칙입니다. backend는 화면 표시용으로, gateway는 집행용으로
각자 구현하므로, 규칙이 갈리면 "화면에는 허용인데 실제로는 차단"이 됩니다.

### 허용 모델 (3층)

```text
1) 소유자 기본
     user_allowed_models 행 있음  → 그 목록 (팀 정책 덮어씀)
     행 0개                        → team_allowed_models
     team_allowed_models 도 0개    → 카탈로그의 ACTIVE 전체
2) VK 축소
     virtual_key_allowed_models 행 있음 → 1)과 교집합
     행 0개                             → 1) 그대로
3) INACTIVE alias 는 어느 층에 있든 제외
```

"행 0개"의 의미가 층마다 다릅니다. user 층의 0개는 *폴백*, team 층의 0개는 *제한 없음*,
VK 층의 0개는 *축소 없음*입니다.

### 예산 (05)

```text
기간 = UTC 기준 월, "YYYY-MM"
1) 사용자 예산이 설정되어 있으면 → 사용자 소진 ≥ 사용자 한도 → 정책 적용
2) 팀 예산이 설정되어 있으면     → 팀 소진 ≥ 팀 한도         → 정책 적용
3) 둘 다 미설정                   → 통과
두 예산은 동시에 검사합니다(사용자가 남아도 팀이 소진되면 차단).
정책: HARD_BLOCK → 429 budget_exceeded / SOFT_WARN → 통과 + 경고 기록
```

### Rate limit (06)

```text
(A) 주체 축: VIRTUAL_KEY > USER > TEAM 중 가장 구체적인 정의
              각 한도(rpm/tpm/concurrency) 별로 독립 폴백. NULL = "정의 안 함"
              같은 한도 종류를 합산하거나 최소값을 취하지 않음
(B) 전역 축: GLOBAL(model_alias) 정의. 주체 축과 별개로 항상 함께 검사
둘 다 통과해야 요청이 진행됩니다.
```

## C4. DB 접근 경계

| 스키마 | backend | gateway |
|---|---|---|
| `auth` | CRUD | SELECT + `virtual_keys.last_used_at` UPDATE |
| `model` | CRUD | SELECT |
| `budget` | `budget_configs` CRUD, `budget_usages` SELECT(+재시드) | SELECT + `budget_usages` UPSERT |
| `usage` | SELECT + 집계 테이블 쓰기 | `usage_events` INSERT |
| `audit` | CRUD | 접근 없음 |

- DB 역할 `backend_app` / `gateway_app`에 위 권한만 GRANT합니다. 권한 정의는 backend의
  `backend/db/init/03_grants.sql`이 소유합니다.
- **Alembic 마이그레이션의 단일 소유자는 backend입니다.** gateway는 같은 스키마를 읽되 정의하지 않습니다.
- `last_used_at`은 매 요청 UPDATE가 아니라 분 단위 스로틀링으로 씁니다(쓰기 증폭 방지).

## C5. usage 이벤트

`usage.usage_events`의 컬럼은 01 문서에 정의되어 있습니다. 스키마는 backend가 마이그레이션으로
정의하고, **내용은 gateway가 결정**합니다. 합의가 필요한 지점:

- `request_id`는 UNIQUE입니다. 재시도 시 중복 INSERT가 나지 않아야 합니다.
- 실패 요청도 기록합니다(`status ∈ {SUCCESS, ERROR, TIMEOUT}`).
- `user_id`는 NULL 가능합니다. `TEAM` 소유 VK 호출은 사람에 귀속되지 않습니다.
- `dialect`를 값으로 기록합니다. 집계는 방언 중립이어야 하지만, 방언별 분해도 가능해야 합니다.
- 토큰 수는 provider 응답값을 우선 쓰고, 없어서 추정한 경우 `estimated_usage=true`로 표시합니다.
- `estimated_cost_usd`는 기록 시점 단가로 계산하고, 어떤 단가를 썼는지 `pricing_id`로 남깁니다.
- **정책 거절(401 / 403 / 429)은 `usage_events`에 기록하지 않습니다.** provider 호출이 없었으므로
  비용도 토큰도 없고, 집계 테이블에 0 행을 대량으로 만들면 대시보드 쿼리가 전부 이를 걸러내야 합니다.
  대신 `usage.auth_events`(신설 예정, [09](09-gateway-contract-response.md) S4)로 갑니다.
  즉 실패의 기록 위치는 둘입니다 — provider를 부른 실패는 `usage_events`, 정책이 막은 거절은 `auth_events`.
- **기록 경로 확정**: gateway가 응답 반환 후 백그라운드로 직접 INSERT하고, 실패 시 메모리 스풀에
  넣어 재시도합니다(`ON CONFLICT (request_id) DO NOTHING`). 별도 worker를 두지 않습니다.
- `client` 컬럼은 신설 예정입니다([09](09-gateway-contract-response.md) S3).

## C6. 오류 코드

gateway가 각 방언의 오류 형식으로 변환하더라도, 내부 구분은 유지합니다(ADR-0003).

| 내부 코드 | 상태 | 의미 |
|---|---|---|
| `invalid_virtual_key` | 401 | 키 없음/폐기/만료 |
| `model_not_allowed` | 403 | 허용 모델 정책 위반 |
| `model_inactive` | 404 | 카탈로그에 없거나 INACTIVE |
| `budget_exceeded` | 429 | 예산 소진 (HARD_BLOCK) |
| `rate_limit_exceeded` | 429 | rate limit 초과 (`Retry-After` 포함) |
| `dialect_not_supported` | 400 | 그 모델이 지원하지 않는 방언 |
| `unsupported_field` | 400 | 미지원 필드 (조용히 무시하지 않음) |

## 합의 체크리스트

gateway 브랜치 회신 완료(2026-09-06). 상세와 후속 항목은 [09](09-gateway-contract-response.md).

- [x] C1 키 포맷과 `key_hash` 산출식
- [x] C1 인증 통과 조건과 상태 전이
- [x] C2 캐시 키 이름과 TTL 상한 — 정책 캐시 300s 확정, gateway 전용 키 2종 추가
- [~] C2 집행 카운터 키 이름 — **조건부.** cluster mode hash tag 필요 여부는 Phase 4에서 확정
- [x] C3 세 해석 규칙 (허용 모델 / 예산 / rate limit)
- [x] C4 DB 역할과 권한 범위 — `usage.auth_events` INSERT GRANT 추가 필요
- [x] C5 usage 이벤트 컬럼 — 정책 거절은 `auth_events` 분리, `client` 컬럼 추가
- [x] C6 내부 오류 코드

**미완결 항목**: 스키마 변경 S1~S4 반영, Q1~Q5 확인.
