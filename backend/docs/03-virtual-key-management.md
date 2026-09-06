# 03. Virtual Key Management

| 항목 | 값 |
|---|---|
| 대상 | VK 발급·로테이션·폐기·감사, 키 저장 방식 |
| 상위 기준 | [docs/virtual-key-management.md](../../docs/virtual-key-management.md), [00](00-admin-api-architecture.md), [01](01-data-model.md) |
| 공유 계약 | VK 포맷, `key_hash` 산출식, 상태 전이, 캐시 키 — **gateway와 합의 필요** |

## Objective

실제 Bedrock 자격 증명을 배포하지 않고, gateway 전용 Virtual Key(VK)를 발급합니다.
VK는 인증 수단이자 정책 부착점이며, 발급·사용·로테이션·폐기 전 과정이 추적 가능해야 합니다.

## Key Format

```text
vk_<env>_<base62(32 bytes)>
예: vk_live_7Kq2ZpN4rT9wXcE1mHsA0bLdVfYuGjQi
```

- `env` 세그먼트(`live` / `dev`)로 환경 간 오배포를 눈으로 걸러냅니다.
- 엔트로피는 32바이트(256비트) CSPRNG(`secrets.token_bytes`)입니다.
- **표시용 prefix**는 `vk_<env>_` + 랜덤 앞 6자입니다. 예: `vk_live_7Kq2Zp`.
  UI와 로그에는 이 값만 나옵니다.
- 원문은 **발급 응답에서 단 한 번만** 반환되고, 이후 어떤 API로도 다시 조회할 수 없습니다.

## Key Storage — 해시 저장

`auth.virtual_keys`는 `key_hash = sha256(raw_key)`(hex 64자)와 `key_prefix`만 저장합니다.
원문도, 원문의 암호문도 저장하지 않습니다.

근거:

- 관리자에게 원문을 다시 보여주는 기능은 **요구사항이 아니고, 두면 안 되는 기능**입니다.
  [virtual-key-management.md](../../docs/virtual-key-management.md)는 "키 원문 최소 노출"과
  "UI에는 마스킹된 값만"을 명시합니다. 분실 시 복구는 로테이션으로 해결합니다.
- 암호화 저장을 택하면 DEK 관리(KMS, 키 로테이션, 다중 버전 복호화)가 통째로 따라옵니다.
  그 복잡도를 지불할 이유가 "원문 재조회"뿐인데 그 기능을 만들지 않을 것이므로 지불하지 않습니다.
- gateway의 인증 조회 키가 `sha256(raw_key)`이므로, 해시를 컬럼으로 들고 있으면 **폐기 시
  캐시 키를 즉시 계산**할 수 있습니다. 암호문만 있으면 폐기할 때마다 복호화해야 합니다.

키 대조는 인덱스 조회(`WHERE key_hash = $1`)입니다. SHA-256 단독은 저엔트로피 비밀번호에는
부적합하지만, 여기서는 대상이 256비트 랜덤 값이므로 사전 공격·무차별 대입이 성립하지 않습니다.
느린 KDF는 요청 경로 지연만 추가합니다.

> **공유 계약**: 해시 알고리즘과 입력(원문 문자열 그대로, 인코딩 UTF-8)은 gateway와 동일해야 합니다.
> 한쪽만 바꾸면 전 키가 인증 실패합니다. 변경은 ADR 대상입니다.

## Ownership

VK는 `owner_type`(`TEAM` | `USER`) + `owner_id`로 귀속합니다.

| 소유 형태 | 용도 | 사용량 귀속 |
|---|---|---|
| `USER` | 개인이 쓰는 키 | user + 그 사용자의 team |
| `TEAM` | 팀 공용 서비스/배치가 쓰는 키 | team만. 사용량 이벤트의 `user_id`는 NULL |

- `USER` 소유 키도 `team_id`를 비정규화 저장합니다. 팀 축 집계와 인가 판정이 매 요청 조인을
  하지 않게 하기 위해서입니다. 사용자 팀 이동 시 이 값을 갱신합니다(02 문서).
- **팀 미배정 사용자에게는 VK를 발급할 수 없습니다.** `virtual_keys.team_id`가 NOT NULL이고,
  팀 없는 사용량은 예산·rate limit·집계의 어느 축에도 붙지 않기 때문입니다. 400 `owner_has_no_team`.
- `TEAM` 소유 키의 사용량은 사용자 축에 잡히지 않습니다. 대시보드에서 "팀 공용 키" 항목으로
  따로 보이게 합니다. 사람에게 귀속되지 않는 사용량이 조용히 사라지면 안 됩니다.

## Lifecycle

```text
        발급
          │
          ▼
      [ACTIVE] ──── 로테이션 ────▶ [ROTATED] ──(유예 만료)──▶ [REVOKED]
          │                            │
          │                            └── 이 상태에서도 유예 기간 동안 인증 성공
          ├──── 폐기 ────▶ [REVOKED]      (client 전환용)
          │
          └──── 만료 ────▶ [EXPIRED]
```

상태 전이 규칙 **[공유 계약]**:

| from | to | 트리거 | 인증 가능 |
|---|---|---|---|
| — | `ACTIVE` | 발급 | 예 |
| `ACTIVE` | `ROTATED` | 로테이션 | **유예 기간 동안만** 예 |
| `ACTIVE` | `REVOKED` | 폐기 / 사용자 비활성화 / 팀 일괄 폐기 | 아니오 (즉시) |
| `ACTIVE` | `EXPIRED` | `expires_at` 경과 | 아니오 |
| `ROTATED` | `REVOKED` | 유예 만료 (job) 또는 수동 폐기 | 아니오 |
| `REVOKED` | * | — | 재활성화 없음 |
| `EXPIRED` | * | — | 재활성화 없음. 새 키를 발급 |

- gateway는 `ACTIVE`와 "유예 중인 `ROTATED`"만 통과시킵니다. 판정 근거는 캐시에 실린
  상태와 `expires_at`이며, 캐시가 없으면 DB를 봅니다.
- 폐기는 **즉시 반영**되어야 합니다(문서 요구사항). 따라서 폐기 시 캐시 키 삭제는 선택이 아니라
  필수이고, 삭제 실패는 응답에 드러내고 실패 테이블에 기록합니다.

## Expiry

- 발급 시 `expires_at`은 필수 입력이며 상한을 둡니다(기본 상한 365일, 설정값).
- 무기한 키는 API로 만들 수 없습니다. 스키마는 NULL을 허용하지만 이는 마이그레이션 유입 데이터용입니다.
- 만료 처리는 두 겹입니다.
  1. gateway가 요청 시점에 `expires_at`을 확인해 거절 (진실의 원천)
  2. backend의 주기 job이 `ACTIVE` + `expires_at < now()` 행을 `EXPIRED`로 옮기고 캐시를 지움 (표시 정합성)
- 만료 임박 키 조회 API(`?expires_before=`)를 제공해 운영자가 로테이션을 계획할 수 있게 합니다.

## Rotation

로테이션은 "폐기 후 재발급"이 아니라 **유예 기간을 둔 교체**입니다. 무중단 전환이 목적입니다.

```http
POST /api/v1/virtual-keys/{key_id}/rotate
{"grace_period_hours": 24, "reason": "정기 로테이션"}
```

1. 새 VK를 발급합니다. `rotated_from_id = {key_id}`.
2. 기존 키를 `ROTATED`로 바꾸고 `expires_at = now() + grace_period`로 당깁니다.
   (원래 만료가 더 이르면 그 값을 유지합니다 — 로테이션이 수명을 연장하면 안 됩니다.)
3. 두 키 모두의 캐시 키를 삭제합니다.
4. 감사 로그에 전후 키 id를 남깁니다.

- `grace_period_hours`는 0~168(7일)로 제한합니다. 0이면 즉시 `REVOKED`와 같습니다.
- 응답에 새 키 원문이 포함됩니다. 이것이 원문을 볼 수 있는 유일한 다른 경로입니다.
- 로테이션 체인은 `rotated_from_id`로 추적합니다. 감사 API가 체인을 따라 이력을 보여줍니다.
- 유예가 끝난 `ROTATED` 키는 주기 job이 `REVOKED`로 내립니다.

## Per-key Model Restriction

VK는 소유자 정책보다 **좁게만** 만들 수 있습니다.

```text
유효 허용 모델 = (VK 허용 목록) ∩ (사용자 override 있으면 사용자 목록, 없으면 팀 목록)
```

- VK 허용 목록이 비어 있으면 소유자 정책을 그대로 씁니다("축소 없음").
- 소유자 정책에 없는 alias를 VK에 넣으려 하면 400 `model_not_allowed_for_owner`로 거절합니다.
  나중에 소유자 정책이 좁아지면 교집합이 자동으로 줄어들므로, 저장 시점에만 검증하고
  집행 시점에는 항상 교집합을 다시 계산합니다.
- 해석 규칙 상세는 04 문서.

## API

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `POST` | `/virtual-keys` | ADMIN / 팀장(자기 팀) | 발급. **원문 1회 반환** |
| `GET` | `/virtual-keys` | ADMIN / 팀장 / 본인 | 목록. `?owner_type=&owner_id=&team_id=&status=&expires_before=&q=` |
| `GET` | `/virtual-keys/{key_id}` | 동상 | 단건 (원문 없음) |
| `PATCH` | `/virtual-keys/{key_id}` | ADMIN / 팀장 | 이름, 허용 모델, `expires_at` 단축만 |
| `POST` | `/virtual-keys/{key_id}/rotate` | ADMIN / 팀장 | 로테이션 |
| `DELETE` | `/virtual-keys/{key_id}` | ADMIN / 팀장 / 본인 | 폐기(204). `?reason=` |
| `POST` | `/teams/{team_id}/virtual-keys/revoke-all` | ADMIN | 팀 전체 즉시 폐기 (사고 대응) |
| `GET` | `/virtual-keys/{key_id}/audit` | ADMIN / 팀장 | 이 키와 로테이션 체인의 감사 이력 |
| `GET` | `/virtual-keys/{key_id}/usage` | ADMIN / 팀장 / 본인 | 이 키의 사용량 요약(집계 테이블) |

### 발급 요청/응답

```http
POST /api/v1/virtual-keys
{
  "name": "search-service-prod",
  "owner_type": "TEAM",
  "owner_id": "9f2c...",
  "expires_at": "2027-03-01T00:00:00Z",
  "allowed_model_aliases": ["claude-sonnet-4", "nova-pro"]
}
```

```json
{
  "id": "b71a...",
  "name": "search-service-prod",
  "virtual_key": "vk_live_7Kq2ZpN4rT9wXcE1mHsA0bLdVfYuGjQi",
  "key_prefix": "vk_live_7Kq2Zp",
  "owner_type": "TEAM",
  "owner_id": "9f2c...",
  "team_id": "9f2c...",
  "status": "ACTIVE",
  "expires_at": "2027-03-01T00:00:00Z",
  "allowed_model_aliases": ["claude-sonnet-4", "nova-pro"],
  "created_at": "2026-09-06T04:11:20Z"
}
```

- `virtual_key` 필드는 **발급과 로테이션 응답에만** 존재합니다. 목록·단건 조회 응답 스키마에는
  아예 필드가 없습니다(빈 값으로 두면 언젠가 채워집니다).
- 발급 응답을 로깅하지 않습니다. 응답 본문 로깅 미들웨어를 두지 않는 이유입니다.

### 폐기

```http
DELETE /api/v1/virtual-keys/{key_id}?reason=OFFBOARDING
```

- 이미 `REVOKED`인 키에 대한 폐기는 멱등하게 204를 반환합니다(재시도 안전).
- `reason`은 자유 문자열이 아니라 enum 후보값 + 자유 메모입니다:
  `LOST`, `OFFBOARDING`, `POLICY_VIOLATION`, `INCIDENT`, `ROTATION`, `OTHER`.
  감사 요구사항이 "폐기 사유와 수행 주체"를 요구하므로 사유는 필수입니다.

## Enforcement Contract (gateway와 공유)

> 아래 키 이름과 페이로드는 **gateway가 소유**합니다. backend는 삭제만 합니다. 착수 전 합의 대상입니다.

| 캐시 키(제안) | 내용 | 채우는 주체 |
|---|---|---|
| `vk:auth:{key_hash}` | 인증 컨텍스트: `virtual_key_id`, `owner_type`, `owner_id`, `team_id`, `user_id`, `status`, `expires_at`, `allowed_model_aliases` | gateway |

backend가 이 키를 삭제하는 시점:

- VK 발급 (동일 해시가 있을 리 없지만 방어적으로)
- VK 폐기 / 로테이션 / 만료 처리
- VK 허용 모델 변경
- 소유자(사용자/팀)의 허용 모델·팀 소속 변경 → 영향 받는 VK 전부

**팬아웃 계산은 DB에서 합니다.** 팀 정책이 바뀌면 `SELECT key_hash FROM auth.virtual_keys
WHERE team_id = $1 AND status IN ('ACTIVE','ROTATED')`로 대상 해시를 얻어 정확히 삭제합니다.
Redis `SCAN` 패턴 삭제는 쓰지 않습니다(키스페이스 전체를 훑고, 다른 plane의 키를 지울 위험).

`last_used_at`은 gateway가 UPDATE합니다. backend는 읽기만 하며, 이 값으로
"장기 미사용 키" 목록을 제공합니다(`GET /virtual-keys?unused_since=`).

## Audit

VK 관련 감사는 `audit.audit_logs`에 `resource_type='virtual_key'`로 남깁니다.

| action | changes에 남기는 것 |
|---|---|
| `CREATE_VIRTUAL_KEY` | `after`: name, owner, key_prefix, expires_at, allowed_models |
| `ROTATE_VIRTUAL_KEY` | `before`: 구 키 id/prefix, `after`: 신 키 id/prefix, 유예 시간 |
| `REVOKE_VIRTUAL_KEY` | `before`: status, `after`: REVOKED + reason |
| `UPDATE_VIRTUAL_KEY` | 변경 필드 before/after |
| `REVOKE_TEAM_VIRTUAL_KEYS` | 대상 팀, 폐기 건수 |
| `EXPIRE_VIRTUAL_KEY` | job이 actor. `actor_user_id`는 시스템 UUID |

- `changes`에 `key_hash`나 원문을 넣지 않습니다. `key_prefix`만 남깁니다.
- `GET /virtual-keys/{id}/audit`는 해당 키 + `rotated_from_id` 체인 전체의 이력을 시간순으로 반환합니다.
  "이 키의 조상은 무엇이고 왜 교체됐는가"가 한 화면에서 보여야 합니다.

### 인증 이벤트는 여기 없습니다

"어떤 키가 어떤 모델을 언제 호출했는가"와 인증 실패 이력은 **data plane의 기록**입니다.
`usage.usage_events`(성공/실패 포함)가 원천이고, backend는 조회 API만 제공합니다.
control plane 감사 로그에 인증 이벤트를 섞으면 저 QPS 테이블에 고 QPS 쓰기가 들어옵니다.

## Background Jobs

| job | 주기 | 내용 |
|---|---|---|
| `expire_virtual_keys` | 5분 | `ACTIVE` + 만료 경과 → `EXPIRED`, 캐시 삭제, 감사 기록 |
| `close_rotated_keys` | 5분 | `ROTATED` + 유예 경과 → `REVOKED`, 캐시 삭제 |
| `retry_cache_invalidation` | 1분 | `audit.cache_invalidation_failures` 미해결 재시도 |

- job은 API 프로세스와 같은 이미지, 다른 엔트리포인트로 실행합니다(Deployment 분리).
- 다중 replica에서 중복 실행되지 않도록 PostgreSQL advisory lock으로 단일 실행을 보장합니다.

## Operational Guidance

- UI 기본 표시는 항상 `key_prefix`입니다. 원문 표시 화면은 발급 직후 모달 1회뿐입니다.
- 장기 미사용 키 목록과 만료 임박 목록을 운영 화면 상단에 노출합니다.
- 팀 일괄 폐기(`revoke-all`)는 **되돌릴 수 없고 client가 즉시 깨지는** 조작입니다.
  요청 본문에 팀 이름 확인 문자열을 요구하고, 감사 로그에 폐기 건수를 남깁니다.

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| 저장 | AES-256-GCM 암호문 + 다중 키 버전 | `sha256` 해시 | 원문 재조회 기능을 만들지 않습니다. DEK 관리 비용 제거, 폐기 시 복호화 불필요 |
| 수명 | 1~24시간, SSO 교환으로 자동 재발급 | 장기(상한 365일), 관리자 발급 | 우리 client는 SSO 세션이 없는 내부 서비스도 포함합니다. 짧은 TTL은 SSO 교환 경로가 생긴 뒤 옵션으로 추가 |
| 활성 키 수 | 사용자당 1개(발급 시 기존 키 만료) | 다중 허용 | 무중단 로테이션과 서비스별 키 분리를 위해 필요합니다 |
| 로테이션 | 사실상 재발급 | 유예 기간 있는 교체 + 체인 추적 | 문서의 "점진 전환"과 "전후 관계 연결" 요구사항 |
| 소유 | 사용자 전용 | 사용자 + 팀 | 문서가 팀 귀속 키를 요구합니다 |
| 캐시 | admin-api가 인증 컨텍스트를 Redis에 직접 SET | backend는 DEL만 | AGENTS.md 캐시 소유권 |
| 팬아웃 무효화 | `SCAN` 패턴 삭제 | DB에서 대상 해시 조회 후 정확 삭제 | 키스페이스 스캔 비용과 오삭제 위험 |

## 미결정

- SSO 세션 기반 단기 VK 교환 엔드포인트(`POST /auth/exchange` 형태)를 둘지. 관리자 인증 ADR과 묶입니다.
- `TEAM` 소유 키의 사용량을 사용자 축에서 어떻게 표현할지(별도 버킷 vs 발급자 귀속). 05·07에서 다룹니다.
