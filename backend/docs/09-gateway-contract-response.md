# 09. Gateway 계약 회신과 스키마 변경 요청

| 항목 | 값 |
|---|---|
| 상태 | **backend 회신 (초안). Q1~Q5는 gateway 확인 대기** |
| 대상 | [08-shared-contracts.md](08-shared-contracts.md) 합의 결과 수용, gateway의 스키마 변경 요청 S1~S4 처리 |
| 출처 | `feat/gateway` worktree의 `gateway/docs/` (2026-09-06 시점, 미커밋 문서 6건) |

## 이 문서의 목적

gateway 브랜치가 [08](08-shared-contracts.md)의 합의 체크리스트에 응답하고, 동시에 네 건의
**스키마 변경**을 요청했습니다. 스키마는 backend가 소유하므로 이 요청의 처리 주체는 backend입니다.

이 문서는 세 가지를 남깁니다.

1. gateway의 구현 진행도와 빌드 순서 — 언제까지 무엇이 필요한지
2. C1~C6 합의 결과와, 그 과정에서 **좁혀지거나 추가된 내용**
3. S1~S4 각각에 대한 backend의 판단과 반영 방법

## gateway 구현 진행도

| 항목 | 상태 |
|---|---|
| 코드 | **없음.** 설계 문서만 존재 |
| 문서 | 6건 / 1,381줄 (`gateway/docs/`). 아직 **커밋되지 않음** |
| 브랜치 위치 | `237672d` — backend Phase 1 커밋이 반영되지 않은 상태 |
| 결과 | gateway worktree에서 `backend/docs/` 링크가 아직 해석되지 않습니다 |

### gateway 빌드 순서와 backend 의존

| 단계 | 내용 | backend 의존 |
|---|---|---|
| M1 | 골격 — app factory, Redis/DB 연결, pure ASGI 미들웨어 | 없음 |
| M2 | VK 인증 + 허용 모델 3층 해석 + client 식별 | **Phase 1 스키마** (완료) |
| M3 | 모델 해석 (`alias → ModelConfig`) | **Phase 1 스키마** (완료) |
| M4 | Bedrock 호출 + Anthropic Messages 방언 | 없음 |
| M5 | OpenAI 호환 방언 + usage/auth 이벤트 기록 | **S3, S4** |
| M6 | Mantle adapter | **S1, S2** |

- **지금 막혀 있는 것은 없습니다.** M1~M4는 Phase 1 스키마만으로 진행됩니다.
- S3·S4는 M5, S1·S2는 M6의 선행 조건입니다. 즉 backend의 스키마 작업은 gateway가 M4를
  끝내기 전에만 들어가면 됩니다.
- 다만 **S4는 우선순위가 높습니다.** 없으면 정책 거절(401/403/429)이 어디에도 기록되지 않아
  [virtual-key-management.md](../../docs/virtual-key-management.md)의 "성공/실패 인증 이벤트를
  남긴다"가 충족되지 않습니다.

## C1~C6 합의 결과

| 항목 | gateway 회신 | backend 확인 |
|---|---|---|
| C1 키 포맷·`key_hash` | 수용 | 그대로 |
| C1 인증 통과 조건·상태 전이 | 수용 | 그대로 |
| C2 캐시 키 이름 | 수용 + gateway 전용 키 2종 추가 | 수용 (아래 Q1) |
| C2 TTL 상한 | 정책 캐시 300s / `policy:model:list` 60s / `vk:miss` 30s | 수용 |
| C2 집행 카운터 키 | 조건부 — cluster mode hash tag 여부는 Phase 4 | 수용. Phase 4에서 `cache_keys.rate_limit_counter()` 동시 갱신 |
| C3 허용 모델 3층 | 수용. `policy/allowed_models.resolve()`와 동일 규칙 | 그대로 |
| C3 예산·rate limit | 수용 (집행은 Phase 4) | 그대로 |
| C4 DB 역할·권한 | 수용. S4 반영 시 INSERT GRANT 추가 필요 | 수용 (아래 작업 목록) |
| C5 usage 이벤트 컬럼 | 수용 + S3. 기록 경로는 gateway 직접 INSERT | 수용 |
| C5 429 미기록 | **확장** — 401/403/429 전부 `usage_events` 제외, `auth_events`로 | 수용 (파급은 아래) |
| C6 오류 코드 | 수용. 방언별 매핑표에 반영 | 그대로 |

### 합의 과정에서 좁혀지거나 추가된 것

계약이 **그대로 통과한 게 아니라 조정된** 지점입니다. 여기가 나중에 기억나지 않으면 서로 다른
전제를 갖게 됩니다.

**1) "폐기는 즉시 반영" 의 정확한 범위**

backend의 [03](03-virtual-key-management.md)은 "폐기된 키는 즉시 인증 거부"를 요구합니다.
캐시가 있는 이상 이 말은 다음으로 좁혀집니다.

- 정상 경로: backend가 커밋 후 `vk:auth` 키를 DEL → **다음 요청부터 즉시 거부**
- 무효화 실패: gateway의 TTL 상한(300s)까지 지연. 그 이상은 아님

backend의 `DELETE /virtual-keys/{id}` 는 이미 `x-cache-invalidated` 헤더로 삭제 성공 여부를
드러냅니다. 지연 상한이 존재한다는 사실을 운영 화면에도 표시해야 합니다.

**2) `vk:auth` payload에 `idp_subject` 추가**

C2 원안에 없던 필드입니다. gateway가 `auth.users.idp_subject`를 스냅샷에 넣고, Bedrock 요청의
`metadata.user_id`로 전달해 provider 측 남용 탐지에 붙입니다. `gateway_app`은 이미 `auth`에
SELECT 권한이 있어 **권한 변경은 필요 없습니다**. (검토 필요 사항은 Q4)

**3) `allowed_model_aliases`는 항상 최종 목록**

gateway는 캐시에 "전체 허용"(`None`)을 넣지 않고 해석이 끝난 목록만 굳힙니다. 빈 목록은
"이 키로 쓸 수 있는 모델 없음"이라는 유효한 상태입니다. backend의
`policy/allowed_models.resolve()` 반환값과 의미가 일치합니다.

**4) 실패 요청의 기록 위치가 둘로 나뉨**

| 실패 종류 | 기록 위치 |
|---|---|
| provider 호출이 일어난 실패 (`ERROR` / `TIMEOUT`) | `usage.usage_events` |
| 정책이 막은 거절 (401 / 403 / 429) | `usage.auth_events` (S4) |

[usage-and-cost-observability.md](../../docs/usage-and-cost-observability.md)는 "실패 요청도
집계 대상에 포함"이라고만 적혀 있습니다. 이제 실패가 두 테이블로 나뉘므로 **대시보드의 '실패율'
정의가 두 테이블을 합치는 형태**가 되어야 합니다. M7 설계에서 반영합니다.

**5) 비용 기록 경로 결정 종결**

gateway가 `usage_events`에 **직접 INSERT**하고, 실패 시 메모리 스풀에 넣어 재시도합니다.
Redis Stream + 별도 worker는 채택하지 않았습니다.
[implementation-plan.md](../../docs/implementation-plan.md)의 Open Decision "비용 기록 경로"가
이것으로 닫힙니다 → **ADR 후보** (확정 시 `main`의 `docs/`에 번호를 받습니다).

backend 쪽 파급: 별도 cost-recorder 컴포넌트를 만들지 않습니다. 대신 스풀은 유실 가능한
버퍼이므로 **드롭이 곧 비용 과소 집계**입니다. [05](05-budget-management.md)의
`verify_budget_counters` job(Redis vs DB 정합성 검증)의 중요도가 올라갑니다.

## 스키마 변경 요청 S1~S4

네 건 모두 **수용**합니다. 아래는 각각의 판단 근거와 반영 방법입니다.
반영은 마이그레이션 `0004`(및 필요 시 `0005`)로 한 번에 처리합니다.

### S1 — `model.provider` enum에 `BEDROCK_MANTLE` 추가

**요청**: Mantle은 전송 방식(HTTPS + bearer)과 IAM 네임스페이스(`bedrock-mantle:`)가 Bedrock
native와 다른 별도 백엔드다.

**판단**: 수용. `api_format`의 변형이 아니라 provider 축의 값이 맞습니다. 같은 role로
`bedrock:InvokeModel`만 주면 Mantle 호출이 실패한다는 것은 **권한 경계가 다르다**는 뜻이고,
권한 경계가 다른 것을 같은 provider 값으로 묶으면 IRSA 정책을 모델별로 나눌 수 없습니다.

[01](01-data-model.md)에서 "provider는 지금 `BEDROCK` 하나지만 enum으로 둔다. 나중에 컬럼
타입을 바꾸는 것보다 값을 추가하는 편이 싸다"고 적어둔 판단이 그대로 적용됩니다.

**반영**

```sql
ALTER TYPE model.provider ADD VALUE IF NOT EXISTS 'BEDROCK_MANTLE';
```

- PostgreSQL 16이므로 트랜잭션 블록 안에서 실행할 수 있습니다. 다만 **같은 트랜잭션에서 그 값을
  사용할 수는 없습니다.** 값 추가 리비전과 그 값을 쓰는 데이터 변경 리비전을 분리합니다.
- enum 값은 **삭제하지 않습니다**([01](01-data-model.md) 공통 규약). 되돌리려면 새 타입을 만들어
  치환해야 하므로 downgrade는 no-op으로 둡니다.

### S2 — `model.model_aliases.endpoint_url` (text NULL) 추가

**요청**: Mantle 엔드포인트는 모델별 속성이다. 카탈로그 밖(설정)에 두면 운영자가 콘솔에서 볼 수 없다.

**판단**: 수용. 근거에 동의합니다. "어디로 부르는가"는 alias 해석의 결과이고, alias 해석의
원천은 카탈로그입니다. 설정 파일에 두면 카탈로그와 설정이 이원화되어 ADR-0001이 LiteLLM을
버린 이유와 같은 문제가 생깁니다.

**반영**

```sql
ALTER TABLE model.model_aliases ADD COLUMN endpoint_url text NULL;
ALTER TABLE model.model_aliases ADD CONSTRAINT ck_model_endpoint_required
    CHECK (provider <> 'BEDROCK_MANTLE' OR endpoint_url IS NOT NULL);
```

- **CHECK 제약을 함께 겁니다.** Mantle 모델을 endpoint 없이 등록하면 gateway가 첫 호출에서야
  실패합니다. 등록 시점에 막는 편이 낫습니다.
- 반대 방향(`BEDROCK`인데 endpoint_url이 있음)은 막지 않습니다. 향후 VPC endpoint 같은
  용도가 생길 여지를 닫지 않기 위해서입니다.
- API 파급: `ModelCreateRequest` / `ModelUpdateRequest` / `ModelResponse`에 `endpoint_url` 추가,
  스킴 검증(`https://`만 허용)은 애플리케이션 계층에서 합니다.

### S3 — `usage.usage_events.client` (text NULL) 추가

**요청**: 도구별 사용량 분해. 값은 gateway 설정의 등록 화이트리스트로 제한되고, 미등록 값은
`other`로 떨어진다.

**판단**: 수용. 카디널리티 통제(화이트리스트)가 gateway 쪽에 이미 있고, client는 **인가 신호가
아니라 관측 라벨**이라는 신뢰 경계도 명확합니다. 잘못 분류돼도 라벨 하나가 `other`가 될 뿐
권한이 열리지 않는다는 판단에 동의합니다.

**반영**

```sql
ALTER TABLE usage.usage_events ADD COLUMN client text NULL;
```

- 인덱스는 지금 만들지 않습니다. 집계 job이 어떤 축으로 훑는지 M7에서 확정된 뒤 붙입니다.
  쓰기 경로 테이블에 쓰이지 않을 인덱스를 미리 두면 INSERT 비용만 늘어납니다.
- **집계 테이블에는 아직 넣지 않습니다.** 이유는 Q2에 적었습니다.

### S4 — `usage.auth_events` 테이블 신설

**요청**: 정책 거절(401/403/429)을 기록할 자리. `usage_events`에 0 토큰 행을 대량으로 만들지 않기 위해.

**판단**: 수용. backend의 [03](03-virtual-key-management.md)이 이미 "인증 성공/실패 이벤트는
control plane 감사(`audit.audit_logs`)가 아니라 data plane 기록"이라고 경계를 그어 두었고,
S4는 그 경계의 실체입니다. 저 QPS 테이블(`audit_logs`)에 고 QPS 쓰기가 들어오지 않게 하는
같은 이유이기도 합니다.

**반영 (제안 형태에 backend가 두 가지를 더함)**

```text
usage.auth_events
  id                uuid PK
  occurred_at       timestamptz NOT NULL          -- 마지막 발생 시각
  first_occurred_at timestamptz NOT NULL          -- ★ backend 추가
  occurrence_count  int NOT NULL DEFAULT 1        -- ★ backend 추가
  outcome           text NOT NULL
  virtual_key_id    uuid NULL  FK → auth.virtual_keys(id)
  key_hash_prefix   char(8) NULL
  team_id           uuid NULL  FK → auth.teams(id)
  user_id           uuid NULL  FK → auth.users(id)
  client            text NULL
  model_alias       text NULL
  source_ip         inet NULL
  request_id        text NOT NULL
```

**추가한 두 컬럼의 이유**: gateway는 "동일 출처의 연속 실패는 임계까지 집계한 뒤 한 번만 기록"
한다고 했습니다. 그러면 행 하나가 N번의 실패를 대표하는데, 원안에는 **N을 담을 자리가
없습니다.** `request_id`는 그중 한 건만 가리키게 되고, 행 수를 세면 실제 실패 횟수보다 적게
나옵니다. `occurrence_count`와 `first_occurred_at`로 창(window)을 표현합니다.

**`outcome`은 enum이 아니라 text로 둡니다.** C5가 "스키마는 backend가 정의하고 내용은 gateway가
결정한다"이므로, 거절 사유 값이 늘 때마다 backend 마이그레이션을 기다리게 만들면 소유권이
뒤집힙니다. `client` 컬럼과 같은 성격(관측 라벨)이라 잘못된 값이 들어와도 정책이 열리지
않습니다. 알려진 값 집합은 아래에 문서로 고정합니다.

| outcome | 대응 C6 코드 |
|---|---|
| `INVALID_KEY` / `REVOKED` / `EXPIRED` / `OWNER_INACTIVE` | `invalid_virtual_key` |
| `MODEL_NOT_ALLOWED` | `model_not_allowed` |
| `MODEL_INACTIVE` | `model_inactive` |
| `BUDGET_EXCEEDED` | `budget_exceeded` |
| `RATE_LIMITED` | `rate_limit_exceeded` |

**`key_hash_prefix`는 `virtual_keys.key_prefix`와 다른 값입니다.** 전자는 `sha256(원문)`의 앞
8자, 후자는 원문의 표시용 앞부분(`vk_live_7Kq2Zp`)입니다. 이름이 비슷해 혼동하기 쉬우므로
컬럼 주석에 명시합니다. 미등록 키를 묶어 보기 위한 값이고, 8 hex(32비트)로는 원문을 복원할 수 없습니다.

- 인덱스: `(occurred_at)`, `(virtual_key_id, occurred_at)`, `(key_hash_prefix, occurred_at)`.
- GRANT: `gateway_app`에 INSERT, `backend_app`에 SELECT.
  `db/grants/01_table_grants.sql`에 추가합니다.
- 보존 정책: 공격 트래픽에서 가장 빨리 자라는 테이블입니다. 파티셔닝·보존 기간은
  [07](07-implementation-roadmap.md) 미결정 #3(`usage_events` 파티셔닝)과 **같은 결정으로 묶습니다.**

## backend가 gateway에 되묻는 항목

아래는 회신 문서만으로 확정되지 않은 지점입니다. gateway 브랜치의 답이 필요합니다.

### Q1. `policy:model:list` 무효화 주체

gateway 전용 키로 분류되어 있지만, **이 키를 낡게 만드는 주체는 backend**입니다
(alias 생성 / `INACTIVE` 전환). 현재 backend는 `policy:model:{alias}`만 지웁니다.

- (a) 이 키를 공유 키로 옮기고 backend가 함께 DEL — `cache_keys.model_list()` 추가로 끝납니다
- (b) 60초 staleness를 수용 — `/v1/models`에 잠시 남지만 실제 호출은 `model_inactive`로 거절됨

backend는 **(a)를 권합니다.** 비용이 키 하나 더 지우는 것뿐이고, "비활성화했는데 목록에 보인다"는
운영자에게 설명하기 나쁜 상태입니다.

### Q2. `client`를 집계 축에 넣을지

`usage.daily_usage_aggregates`의 PK는
`(bucket_date, team_id, user_id, virtual_key_id, model_alias)`입니다. 여기에 `client`를 더하면
행 수가 **등록 client 수만큼 곱해집니다.**

- 원천 이벤트에만 두면(현재 결정) 도구별 분해는 raw 스캔이라 대시보드에 쓰기 어렵습니다
- 집계 축에 넣으면 분해는 빠르지만 집계 테이블이 커집니다

backend는 M7(집계 설계) 시점에 정하자는 입장이고, 그때까지 S3는 **원천 컬럼으로만** 둡니다.
gateway 쪽에서 "도구별 비용"이 대시보드 1급 지표라는 요구가 있으면 미리 알려주십시오.

### Q3. 등록 client 집합의 소유 위치

client 화이트리스트는 gateway 설정(env/ConfigMap)에 있고 DB에 없습니다. 그러면 admin 콘솔은
**어떤 값이 존재하는지 알 수 없어** 필터 UI를 데이터에서 유추(distinct)하거나 목록을 프론트에
중복 정의해야 합니다.

정책이 아닌 것을 control plane 스키마에 넣지 않는다는 판단에는 동의하므로, backend는
**데이터에서 distinct로 채우는 쪽**을 택하려 합니다. 다만 값 집합이 바뀔 때(gateway 재배포)
콘솔이 뒤늦게 따라간다는 점만 확인해 주십시오.

### Q4. `idp_subject`를 provider metadata로 전달하는 것

`vk:auth` 스냅샷의 `idp_subject`가 Bedrock 요청 `metadata.user_id`로 나갑니다. 이 값은 사내
SSO의 주체 식별자입니다. **사내 정보보호 정책상 외부 provider로 내보낼 수 있는 값인지**
확인이 필요합니다. 안 된다면 대안은 VK id(무의미 UUID) 전달입니다. 남용 탐지 목적에는
그것으로도 충분해 보입니다.

backend 쪽 조치는 없지만, 확인 없이 나가면 되돌리기 어려운 종류의 값이라 적어 둡니다.

### Q5. 스풀 드롭 지표의 노출 경로

usage 기록 실패가 스풀 한도를 넘어 드롭되면 **비용이 과소 집계**됩니다. gateway는 메트릭으로
드러낸다고 했는데, backend 대시보드가 "이 기간 집계는 불완전함"을 표시하려면 그 사실을 읽을
경로가 필요합니다.

- (a) gateway가 드롭 건수를 `usage.auth_events`와 별개의 카운터 테이블에 주기 기록
- (b) backend가 Prometheus를 직접 조회
- (c) 표시하지 않음 (메트릭 알람으로만 운영)

backend는 (a)를 선호하지만 테이블이 하나 더 늘어납니다. Phase 4에서 정해도 됩니다.

## backend 작업 목록

| # | 작업 | 대상 | 선행 조건 |
|---|---|---|---|
| 1 | 마이그레이션 `0004` — S1 enum 값 추가 | `db/versions/` | 없음 |
| 2 | 마이그레이션 `0005` — S2 컬럼 + CHECK, S3 컬럼, S4 테이블 | `db/versions/` | 1 (enum 값과 사용 분리) |
| 3 | `gateway_app` INSERT / `backend_app` SELECT GRANT (`usage.auth_events`) | `db/grants/01_table_grants.sql` | 2 |
| 4 | ORM 모델 반영 (`Provider`, `ModelAlias.endpoint_url`, `UsageEvent.client`, `AuthEvent`) | `src/app/models/` | 2 |
| 5 | 모델 API에 `endpoint_url` 추가 + https 검증 | `schemas/models.py`, `services/model_service.py` | 4 |
| 6 | Q1 확정 시 `cache_keys.model_list()` 추가 및 카탈로그 변경 시 DEL | `core/cache_keys.py`, `services/model_service.py` | Q1 |
| 7 | `auth_events` 조회 API (VK 감사 화면 결합) | `routers/virtual_keys.py` | M7 |
| 8 | 문서 갱신 — 01(스키마), 03(감사), 05(집계 정의), 08(계약 확정) | `docs/` | 2 |

1~5는 gateway M5 착수 전까지 들어가면 됩니다. 6은 Q1 답변에 달려 있고, 7은 M7 범위입니다.

## 상위 문서에 반영해야 할 것

`main` 브랜치에서 처리할 항목입니다(브랜치 규율상 이 worktree에서 고치지 않습니다).

| 문서 | 변경 |
|---|---|
| `docs/implementation-plan.md` | Open Decision "비용 기록 경로" 종결 — gateway 인라인 INSERT + 스풀 |
| `docs/adr-000X` | 위 결정을 ADR로 승격 (ADR 후보) |
| `docs/usage-and-cost-observability.md` | 실패 요청의 기록 위치가 둘로 나뉜 것 반영 (`usage_events` / `auth_events`) |
