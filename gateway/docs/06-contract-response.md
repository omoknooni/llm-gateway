# 06. backend 회신에 대한 답변 (Q1~Q5)

| 항목 | 값 |
|---|---|
| 상태 | **gateway 회신. Q1~Q5 확정, Q5는 방향만** |
| 대상 | backend [09-gateway-contract-response.md](../../backend/docs/09-gateway-contract-response.md) |
| 선행 | [08-shared-contracts.md](../../backend/docs/08-shared-contracts.md) C1~C6 합의 (완료) |

## 이 문서의 목적

backend가 스키마 변경 요청 S1~S4를 모두 수용하면서 다섯 건을 되물었습니다. 이 문서는 그 다섯 건에
답하고, 그중 **Q4가 gateway 설계 자체를 바꾼 결과**를 남깁니다.

## S1~S4 수용 확인

네 건 모두 수용 감사합니다. backend가 반영 과정에서 **원안에 없던 것을 더했고**, 그 부분에 대한
gateway의 확인입니다.

### S2의 CHECK 제약 — 동의

```sql
CHECK (provider <> 'BEDROCK_MANTLE' OR endpoint_url IS NOT NULL)
```

등록 시점에 막는 편이 낫다는 판단에 동의합니다. gateway는 이 제약을 신뢰하되, `ModelConfig`를
만들 때 `provider = BEDROCK_MANTLE AND endpoint_url IS NULL`이면 그 alias를 **해석 실패로 처리**해
`model_inactive`(404)를 반환합니다. 제약은 새로 들어오는 행만 막고, 제약 도입 이전 행이나
직접 SQL로 넣은 행은 막지 못합니다. 두 겹으로 둡니다.

역방향(`BEDROCK`인데 `endpoint_url`이 있음)을 막지 않는 결정에도 동의합니다. gateway의
Bedrock adapter는 이 컬럼을 읽지 않으므로 값이 있어도 무해합니다.

### S4에 backend가 더한 두 컬럼 — 동의, 채우는 규칙은 아래

`occurrence_count` / `first_occurred_at`의 필요성 지적이 정확합니다. 원안대로면 행 수를 세는
쿼리가 실제 실패 횟수보다 적게 나옵니다. gateway가 채우는 규칙을 여기서 고정합니다.

```text
묶음 키 = (outcome, key_hash_prefix, source_ip, client)
창(window) = 60초, 프로세스 로컬

창이 닫힐 때 1행 INSERT:
  first_occurred_at = 창의 첫 실패 시각
  occurred_at       = 창의 마지막 실패 시각
  occurrence_count  = 창 안의 실패 수 (1건뿐이어도 1로 기록)
  request_id        = 창의 **첫** 요청 id
```

- `request_id`가 첫 건인 이유: 그 요청의 로그 라인이 원인을 담고 있어 조사 진입점이 됩니다.
  마지막 건을 가리키면 이미 반복된 뒤의 흔적만 보입니다.
- **창은 프로세스 로컬입니다.** pod가 N개면 같은 시각·같은 출처의 실패가 최대 N행으로 나뉩니다.
  조회 시 행 수가 아니라 **`SUM(occurrence_count)`** 로 집계해 주십시오. 이걸 놓치면 pod 수만큼
  실패가 과소 계상됩니다.
- 기록 지연은 최대 창 길이(60초)입니다. `gateway_app`에 UPDATE 권한을 받아 "첫 건 즉시 INSERT +
  이후 UPDATE"로 만들면 지연이 사라지지만, 여러 pod가 같은 행을 갱신하려면 upsert 키와 경합 처리가
  필요해집니다. **감사·조사 용도에 60초 지연은 무해**하다고 보고 INSERT 전용을 유지합니다.
  즉시성이 필요한 보안 대응은 DB가 아니라 메트릭·알람의 몫입니다.
- pod 종료 시 열려 있는 창은 flush합니다.

### `outcome`을 text로 두는 결정 — 동의

값이 늘 때마다 backend 마이그레이션을 기다리면 "내용은 gateway가 결정한다"(C5)가 뒤집힌다는
논거에 동의합니다. **값 집합은 backend가 [09](../../backend/docs/09-gateway-contract-response.md)에
정리한 표를 그대로 씁니다.** 한 가지만 맞췄습니다.

- 초안의 [01](01-api-entrypoint.md)은 `dialect_not_supported`(400)도 `auth_events`에 기록하는
  것으로 되어 있었습니다. **철회합니다.** 이건 정책 거절이 아니라 잘못된 엔드포인트로 보낸 요청이고,
  "요청 자체가 잘못된 것은 기록하지 않는다"는 우리 원칙과도 어긋났습니다. 결과적으로 `outcome`의
  값 집합이 backend 표와 정확히 일치합니다.

### `key_hash_prefix` ≠ `key_prefix` — 동의

혼동하기 쉬운 이름이 맞습니다. gateway 쪽 문서에도 명시했습니다.

| 값 | 정의 | 예 |
|---|---|---|
| `virtual_keys.key_prefix` | **원문**의 표시용 앞부분 | `vk_live_a1b2c3` |
| `auth_events.key_hash_prefix` | `sha256(원문)`의 앞 8자 | `3f9a1c07` |

## Q1 — `policy:model:list` 무효화 주체

**(a) 채택.** 공유 키로 옮기고 backend가 함께 DEL합니다. 두 가지를 덧붙입니다.

**무효화 트리거는 상태 전환만이 아닙니다.** `/v1/models` 응답에는 각 항목의 `supported_dialects`와
`max_output_tokens`가 실립니다. 따라서 **`model_aliases`의 모든 변경**(생성·수정·상태 전환)에서
이 키를 지워야 합니다. 실무적으로는 `policy:model:{alias}`를 지우는 자리마다 함께 지우면 됩니다.
상태 전환만 트리거로 잡으면 방언 목록이 바뀐 모델이 옛 값으로 남습니다.

**이 키는 표시용만이 아닙니다.** 허용 모델 3층 해석에서 "team 층 0개 → 카탈로그 ACTIVE 전체"의
재료이기도 합니다. 그래서 다음이 성립합니다.

- backend가 이 키를 지워도 **이미 굳어진 `vk:auth` 스냅샷은 TTL 300초까지 옛 목록을 들고 있습니다.**
- 이건 정상 동작입니다. **카탈로그 변경마다 전 VK 캐시를 팬아웃 삭제하지 마십시오.** 새 모델 접근이
  최대 300초 늦게 열릴 뿐이고, 반대 방향(INACTIVE)은 `ScopeCheck`의 `status` 재확인이 잡습니다.
- 즉 카탈로그 변경의 실효 반영 상한은 `/v1/models`가 즉시, 허용 목록이 300초입니다.

**부수 효과: TTL을 60초 → 300초로 올립니다.** 60초로 짧게 잡았던 이유가 "아무도 무효화해 주지
않아서"였고, (a)가 그 이유를 없앱니다. 다른 정책 캐시와 같은 값이 되어 규약이 단순해집니다.

## Q2 — `client`를 집계 축에 넣을지

**넣지 않습니다.** 원천 이벤트 컬럼(S3)으로만 둡니다.

근거는 요구 문서입니다. [usage-and-cost-observability.md](../../docs/usage-and-cost-observability.md)의
집계 축은 시간 / 팀·사용자 / VK / 모델이고,
[leaderboard-and-dashboard.md](../../docs/leaderboard-and-dashboard.md)의 drill-down도
팀·사용자·모델뿐입니다. **client는 어느 문서에도 요구 축으로 없습니다.** 지금 넣으면 요구가 아니라
가능성 때문에 주 집계 테이블의 PK를 바꾸는 셈입니다.

"도구별 비용"이 나중에 대시보드 1급 지표가 되면, 주 집계 테이블을 건드리는 대신 **저차원 테이블을
따로** 두는 쪽을 제안합니다.

```text
usage.daily_client_usage   PK (bucket_date, team_id, client)
    request_count, input_tokens, output_tokens, estimated_cost_usd
```

카드 하나를 채우기에 충분하고, 행 수는 주 집계의 수백분의 일입니다. 이 테이블은 Q3의 값 목록
원천으로도 쓸 수 있습니다. M7에서 필요성이 확인되면 그때 만듭니다.

## Q3 — 등록 client 집합의 소유 위치

**"데이터에서 distinct"는 권하지 않습니다.** S3에서 `client` 인덱스를 만들지 않기로 했으므로
그 조회는 `usage_events` 전체 스캔이 됩니다. 이 테이블은 파티셔닝이 거론될 만큼 커질 예정이고,
그 스캔이 콘솔 필터를 열 때마다 돕니다.

**값 집합을 계약 문서로 고정합니다.** backend가 `auth_events.outcome`을 "text 컬럼 + 문서로 고정한
알려진 값 집합"으로 다루기로 한 것과 같은 방식이고, C6 오류 코드 표도 같은 방식입니다.

| 값 | 대상 |
|---|---|
| `claude-code` | Claude Code CLI |
| `claude-desktop` | Claude 데스크톱 앱 계열 |
| `codex` | OpenAI Codex CLI |
| `openai-sdk` | OpenAI 공식 SDK (python / node) |
| `other` | 분류되지 않음 (예약어) |

- 원본은 [03-client-identification.md](03-client-identification.md)의 "알려진 client 값" 표입니다.
- 값 추가·삭제는 **gateway 설정 변경과 이 표의 갱신이 한 쌍**으로 움직입니다. 계약 문서가 바뀌므로
  backend에 통보되고, 콘솔은 그때 목록을 맞춥니다.
- 콘솔은 이 목록으로 필터를 그리고, 데이터에 없는 값은 0건으로 표시하면 됩니다. 값 집합이 늦게
  따라간다는 지적은 맞지만, 재배포 주기보다 느리게 바뀌는 목록이라 실무상 문제가 되지 않습니다.

동적 목록이 정말 필요해지면 Q2의 `daily_client_usage`가 그대로 distinct 원천이 됩니다.
작은 테이블이라 스캔해도 쌉니다.

## Q4 — `idp_subject`를 provider metadata로 전달

**철회합니다.** 정책 검토를 기다리지 않고 gateway 설계를 바꿉니다.

provider가 `metadata.user_id`에 요구하는 것은 **불투명한 식별자**(uuid·해시 등)이고, 이름·이메일
같은 식별 정보를 넣지 말 것을 명시합니다. 그런데 OIDC `sub`는 IdP 설정에 따라 이메일이나 사번이
그대로 들어옵니다. 사내 IdP는 아직 미확정이므로([07](../../backend/docs/07-implementation-roadmap.md)
미결정 #1) **우리는 이 값이 불투명할지 아닐지를 지금 알 수 없습니다.** 알 수 없는 값을 외부로
내보내는 설계를 유지할 이유가 없습니다.

**대체 값은 VK id가 아니라 사용자 id입니다.**

```text
metadata.user_id = auth_context.user_id        (owner_type = USER)
                 = auth_context.virtual_key_id (owner_type = TEAM — 귀속될 사람이 없음)
```

둘 다 무의미 UUID지만, VK id는 로테이션 때 바뀌어 provider 측 남용 탐지의 연속성이 끊깁니다.
사람은 로테이션을 건너 그대로이므로 사용자 id가 이 목적에 맞습니다.

**파급 (gateway 문서에 이미 반영)**

| 위치 | 변경 |
|---|---|
| `vk:auth` payload | `idp_subject` 필드 **삭제** |
| 인증 쿼리 | `auth.users.idp_subject`를 읽지 않음 |
| gateway가 읽는 컬럼 목록 | `auth.users`에서 `idp_subject` 제외 |
| provider 요청 | `metadata.user_id = user_id ?? virtual_key_id` |
| client가 보낸 `metadata.user_id` / `user` | 파싱은 하되 **provider로 전달하지 않음** (관측용) |

부수 효과가 좋습니다. **Redis 캐시가 더 이상 개인식별정보의 사본이 아닙니다.** C2 payload에서
gateway가 추가했던 유일한 필드가 그대로 사라지므로, `vk:auth`의 내용이 backend 08 문서 원안과
정확히 같아집니다. backend 쪽 조치는 없습니다.

client가 보낸 값을 전달하지 않는 이유도 같은 계열입니다. client가 채우는 값이라 신뢰할 수 없고,
같은 사람이 도구마다 다른 값을 보내면 provider 측 귀속이 흩어집니다.

## Q5 — 스풀 드롭 지표의 노출 경로

**(b)는 배제합니다.** backend가 Prometheus를 직접 조회하면 control plane에 관측 스택 의존과
쿼리 언어가 하나 들어옵니다. 두 plane을 DB·Redis 규약으로만 만나게 해 온 원칙과 어긋납니다.

**(a) 방향에 동의하되, 형태는 일 단위 카운터가 아니라 사건 단위 행을 제안합니다.**

```text
usage.ingest_gaps
  id            uuid PK
  gap_start     timestamptz NOT NULL     -- 첫 드롭 시각
  gap_end       timestamptz NOT NULL     -- 마지막 드롭 시각
  dropped_count int NOT NULL
  recorded_at   timestamptz NOT NULL     -- DB 복구 후 기록한 시각
```

드롭은 DB가 죽어 있는 동안 발생하므로 **그 시점에는 아무것도 쓸 수 없습니다.** DB가 돌아온 시점에
gateway가 사건당 한 행을 INSERT하면 됩니다. 대시보드는 그 구간에 "이 기간 집계는 불완전함" 배너를
띄우면 되고, 폴링도 매일 쓰는 카운터도 필요 없습니다. **정상 운영에서는 행이 0건**입니다.

테이블이 하나 늘지만 Phase 4에서 `verify_budget_counters`(Redis↔DB 정합성 검증)와 함께 설계하면
자연스럽습니다. **확정은 Phase 4로 미룹니다** — 지금 고정하는 것은 (b)를 쓰지 않는다는 것뿐입니다.

## gateway 문서에 반영한 변경

| 문서 | 변경 | 사유 |
|---|---|---|
| [README](README.md) | `policy:model:list`를 공유 정책 캐시로 이동, TTL 300s | Q1 |
| [README](README.md) | 읽는 컬럼에서 `auth.users.idp_subject` 제외 | Q4 |
| [README](README.md) | 스풀 드롭의 사건 단위 기록 방향 명시 | Q5 |
| [01](01-api-entrypoint.md) | `end_user_id`는 관측용, provider 미전달 | Q4 |
| [01](01-api-entrypoint.md) | `dialect_not_supported` 기록 위치 → 기록 없음 | S4 값 집합 정합 |
| [02](02-virtual-key-auth.md) | `AuthContext`에서 `idp_subject` 삭제, 인증 쿼리에서 제외 | Q4 |
| [03](03-client-identification.md) | "알려진 client 값" 표 추가 | Q3 |
| [05](05-provider-invocation.md) | "end-user 귀속" 절 추가 | Q4 |

## backend에 요청하는 후속

| # | 항목 | 대상 |
|---|---|---|
| 1 | `cache_keys.model_list()` 추가 + **`model_aliases`의 모든 변경**에서 DEL | `core/cache_keys.py`, `services/model_service.py` |
| 2 | `auth_events` 조회 시 행 수가 아니라 `SUM(occurrence_count)` 사용 | M7 조회 API |
| 3 | 08 문서의 `vk:auth` payload에서 `idp_subject` 관련 기술 삭제 (원안 복귀) | `docs/08-shared-contracts.md` |
| 4 | 09 문서의 `outcome` 표 유지 — gateway가 `DIALECT_NOT_SUPPORTED`를 추가하지 않음 | 확인만 |

## 남은 미결

| 항목 | 판단 시점 |
|---|---|
| `client`의 집계 축 편입 (Q2 후속) — `daily_client_usage` 신설 여부 | M7 |
| 스풀 드롭 기록의 최종 형태 (Q5) — `usage.ingest_gaps` | 미정 — [08](08-enforcement.md) 의 범위 밖 |
| ~~집행 카운터 키의 cluster mode hash tag 여부~~ | **종결** — 쓰지 않습니다 ([08](08-enforcement.md)) |
| `auth_events` / `usage_events`의 파티셔닝·보존 기간 | 실사용 볼륨 확인 후 |
