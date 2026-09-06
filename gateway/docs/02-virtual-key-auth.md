# 02. Virtual Key 인증

## Objective

client가 제시한 Virtual Key(VK)를 검증해 요청을 **누구의 것으로 볼지** 확정하고, 그 주체가
**어떤 모델을 쓸 수 있는지**까지 한 번에 확정합니다. 실제 AWS 자격 증명은 client에 내려가지 않고
gateway만 IRSA로 얻습니다 ([virtual-key-management.md](../../docs/virtual-key-management.md)).

이 단계의 산출물은 `AuthContext` 하나이며, 이후 모든 단계가 이것만 참조합니다.

계약의 원본은 [backend/docs/08-shared-contracts.md](../../backend/docs/08-shared-contracts.md)의
C1·C3이고, 판정 규칙은 backend의 `policy/virtual_key.py`·`policy/allowed_models.py`와
**같은 결과를 내야 합니다.**

## Key Format (C1, 확정)

발급은 backend가 소유합니다. gateway는 아래 형식만 가정합니다.

```text
vk_<env>_<base62(32 bytes)>        env ∈ {live, dev}
표시용 prefix = vk_<env>_<랜덤 앞 6자>      예) vk_live_a1b2c3
```

- `env` 세그먼트는 환경 간 오배포를 눈으로 걸러내기 위한 것입니다. gateway는 이 값으로 판정하지
  않습니다 — 어느 환경 키인지는 DB에 그 해시가 있느냐로 결정됩니다.
- gateway는 **원문을 저장하지 않고 SHA-256 hex로만 다룹니다.**

```python
key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()   # 소문자 hex 64자
```

`auth.virtual_keys.key_hash`가 이 값이며 UNIQUE입니다. **해시 알고리즘이나 입력 인코딩을
한쪽만 바꾸면 전 키가 인증 실패합니다.** 이 한 줄이 두 plane을 잇는 가장 가는 실입니다.

- **KDF(bcrypt/argon2)를 쓰지 않는 이유**: VK는 사람이 고른 비밀번호가 아니라 256비트 난수라
  사전 공격 대상이 아니고, 요청마다 KDF를 돌리면 hot path가 무너집니다. 해시는 비교용이 아니라
  **조회 키**로 쓰이므로 상수시간 비교 문제도 발생하지 않습니다.
- 마스킹 표시값은 backend가 발급 시 `key_prefix`에 저장합니다. gateway는 만들지도 보여주지도 않습니다.

## 인증 통과 조건 (C1, 확정)

```text
통과 = status ∈ {ACTIVE, ROTATED}
     AND (expires_at IS NULL OR expires_at > now())
     AND 소유자(users / teams)가 is_active
```

- `ROTATED`가 통과하는 것이 중요합니다. 로테이션 유예 기간 동안 구 키가 살아 있어야 점진 전환이
  가능합니다. **유예는 backend가 `expires_at`을 앞당겨 표현**하므로 gateway에 별도 유예 로직이
  없습니다. 조건은 위 세 줄이 전부입니다.
- `REVOKED` / `EXPIRED`는 종료 상태이고 되돌아오지 않습니다.

## Flow

```text
Authorization: Bearer vk_live_...    (또는 x-api-key)
        │
        ▼
  key_hash = sha256(raw).hexdigest()
        │
        ├─ GET vk:miss:{key_hash} ──── hit ──▶ 401 invalid_virtual_key (DB 재조회 없음)
        │
        ├─ GET vk:auth:{key_hash} ──── hit ──▶ AuthContext 복원 ──▶ 통과
        │                                        │
        │                                   miss │
        ▼                                        ▼
  PostgreSQL (short-lived session)
    ① virtual_keys ⋈ users ⋈ teams        (1 왕복)
    ② 허용 모델 3층 재료                    (1 왕복)
        │
        ├─ 통과 조건 불만족 ──▶ SETEX vk:miss 30s ──▶ 401 + auth_events 기록
        │
        ▼
  AuthContext 구성 ──▶ SETEX vk:auth:{key_hash} 300s ──▶ 통과
```

정상 상태에서 요청 경로는 **Redis 왕복 1회**로 끝납니다. DB는 캐시 miss일 때만, 그때도 2회로 끝냅니다.

### ① 주체 조회

```sql
SELECT vk.id, vk.owner_type, vk.owner_id, vk.team_id, vk.status, vk.expires_at,
       u.id AS user_id, u.is_active AS user_active,
       t.is_active AS team_active
  FROM auth.virtual_keys vk
  JOIN auth.teams t ON t.id = vk.team_id
  LEFT JOIN auth.users u ON u.id = vk.owner_id AND vk.owner_type = 'USER'
 WHERE vk.key_hash = :key_hash
```

- `virtual_keys.team_id`는 **비정규화된 컬럼**이라 `USER` 소유 키에도 항상 채워져 있습니다.
  요청 경로에서 팀을 찾으려고 사용자 테이블을 거칠 필요가 없습니다.
- `owner_type = 'TEAM'`이면 `user_id`는 NULL입니다. 이 키의 호출은 사람에 귀속되지 않습니다.

### ② 허용 모델 3층 해석 (C3, 확정)

backend의 `policy/allowed_models.resolve()`와 **글자 그대로 같은 규칙**을 구현합니다.
규칙이 갈리면 "콘솔에는 허용인데 실제로는 차단"이 됩니다.

```text
1) 소유자 기본
     user_allowed_models 행 있음  → 그 목록 (팀 정책을 덮어씀)
     행 0개                        → team_allowed_models
     team_allowed_models 도 0개    → 카탈로그의 ACTIVE 전체
2) VK 축소
     virtual_key_allowed_models 행 있음 → 1) 과 교집합
     행 0개                             → 1) 그대로
3) INACTIVE alias 는 어느 층에 있든 제외 (카탈로그 상태가 최종 관문)
```

**"행 0개"의 의미가 층마다 다릅니다.** user 층의 0개는 *폴백*, team 층의 0개는 *제한 없음*,
VK 층의 0개는 *축소 없음*입니다. 이 셋을 한 번에 "비었으면 전체 허용"으로 뭉뚱그리는 순간
사용자 예외 정책이 조용히 무력화됩니다. **테이블 주도 테스트로 고정합니다.**

- 소유자 층 결과는 `policy:allowed_models:{scope}:{id}`에 캐시합니다(scope = `team` | `user`).
  backend가 정책 변경 시 이 키를 삭제합니다.
- VK 층(`virtual_key_allowed_models`)은 VK에 종속이므로 `vk:auth` 스냅샷 안에 최종 결과로만
  들어갑니다. 별도 캐시를 두지 않습니다.
- 카탈로그의 ACTIVE 전체가 필요한 경우(team 층 0개)에는 `policy:model:list`를 씁니다.

## AuthContext

`vk:auth:{key_hash}`에 직렬화되는 스냅샷입니다. backend가 C2에 적어 둔 payload 형태를 따릅니다.

```python
@dataclass(frozen=True)
class AuthContext:
    virtual_key_id: str
    owner_type: Literal["TEAM", "USER"]
    owner_id: str
    team_id: str                       # VK의 비정규화 컬럼. 항상 존재
    user_id: str | None                # owner_type=USER 일 때만
    status: Literal["ACTIVE", "ROTATED"]
    expires_at: datetime | None
    allowed_model_aliases: list[str]    # 3층 해석의 최종 결과 (빈 목록 = 쓸 수 있는 모델 없음)
```

- `allowed_model_aliases`는 **해석이 끝난 최종 목록**입니다. `None`(전체 허용)을 쓰지 않습니다.
  캐시에 "전체 허용"을 넣으면 카탈로그가 바뀔 때마다 의미가 달라지는데, 그 순간을 캐시가
  알 수 없습니다. 목록으로 굳혀 두면 `policy:model:*` 무효화와 TTL이 그대로 안전망이 됩니다.
- 빈 목록은 유효한 상태입니다. 이 키로는 어떤 모델도 부를 수 없고, 모든 요청이 403입니다.
- 캐시 항목의 **파싱 실패는 예외가 아니라 miss로 취급**해 DB에서 재구성합니다. 필드를 추가했을 때
  구버전 항목 하나가 영구 500이 되는 것을 막는 방어입니다.
- **`idp_subject`(OIDC `sub`)를 스냅샷에 넣지 않습니다.** 초안에서는 이 값을 Bedrock 요청의
  `metadata.user_id`로 전달할 계획이었지만 철회했습니다. 근거와 대체 값은
  [06](06-contract-response.md) Q4에 있습니다. 그 결과 이 캐시에는 개인식별정보가 들어가지 않고,
  인증 쿼리도 `auth.users.idp_subject`를 읽지 않습니다.

## Cache Ownership

**control plane은 캐시 키를 삭제만 하고, 값을 채우는 주체는 gateway입니다**([AGENTS.md](../../AGENTS.md)).
backend는 이미 `CacheInvalidationManager`로 이 규약을 구현했고, 패턴(`SCAN`) 삭제 메서드를
일부러 두지 않았습니다.

| 사건 | backend | gateway |
|---|---|---|
| VK 발급 | DB INSERT | (없음) 첫 요청 때 채움 |
| VK 폐기 / 로테이션 | 커밋 → `DEL vk:auth:{key_hash}` | 다음 요청에서 DB 재조회 → 401 |
| 허용 모델 변경 | 커밋 → `DEL policy:allowed_models:*` + 영향 VK의 `DEL vk:auth:*` | 다음 요청에서 재구성 |
| 사용자 비활성화 / 팀 이동 | 커밋 → 해당 사용자 VK 캐시 삭제 | 다음 요청에서 재구성 |
| 모델 상태 변경 | 커밋 → `DEL policy:model:{alias}` | 다음 요청에서 재구성 |

순서도 계약입니다. **커밋한 뒤에 삭제**합니다. 먼저 지우면 커밋 사이에 들어온 gateway 요청이
옛 값을 다시 채웁니다.

### "즉시 폐기"의 정확한 의미

[virtual-key-management.md](../../docs/virtual-key-management.md)는 "폐기된 키는 즉시 인증 거부"를
요구합니다. 캐시가 있으면 이 말은 다음과 같이 좁혀서 지켜집니다.

- **정상 경로**: backend가 폐기 커밋 후 `vk:auth` 키를 삭제 → 다음 요청부터 즉시 거부.
- **삭제 실패**: backend가 `audit.cache_invalidation_failures`에 기록하고 재시도 job이 처리 → 수 분 내.
- **최악의 경우**(Redis 장애 지속): TTL 300초로 자연 만료.

세 겹이 있으므로 TTL을 더 줄이지 않습니다. 300초는 *실패의 상한*이지 *정상 지연*이 아닙니다.
줄이면 정상 경로의 캐시 적중률만 떨어집니다. 사고 대응 요구가 이 상한을 허용하지 않게 되면
폐기 pub/sub 채널을 ADR로 추가합니다 — 지금 넣으면 plane 간 결합이 하나 늘어납니다.

## Failure Policy — fail-closed

인증은 **확인하지 못하면 거절**합니다.

| 상황 | 동작 |
|---|---|
| Redis 장애, DB 정상 | DB 직접 조회로 통과 (지연 증가 감수) |
| Redis 정상, DB 장애 | 캐시 hit만 통과, miss는 401 |
| 둘 다 장애 | 503 |
| 허용 모델 해석 실패 | **401** — 정책을 모르는 채로 통과시키지 않음 |

마지막 줄이 중요합니다. 허용 모델 조회가 DB 오류로 실패했을 때 "일단 통과"시키면 접근 제한이
조용히 풀립니다. 가용성보다 통제가 우선인 지점입니다.

## 감사와 사용 이력

VK 문서는 성공·실패 인증 이벤트, `last_used_at`, 로테이션 전후 관계 추적을 요구합니다.

| 요구 | 구현 |
|---|---|
| 인증 성공 이력 | `usage.usage_events`의 `virtual_key_id`가 성공 기록 |
| `last_used_at` | **gateway가 직접 UPDATE.** 매 요청이 아니라 분 단위 스로틀링 |
| 인증 실패 이력 | `usage.auth_events` INSERT (신설 요청 S4, [docs/README.md](README.md)) |
| 로테이션 체인 | `virtual_keys.rotated_from_id` — backend 소유. gateway는 관여하지 않음 |

### `last_used_at` 스로틀링

`auth.virtual_keys.last_used_at`은 gateway가 쓰는 유일한 `auth` 컬럼입니다.

```text
프로세스 로컬 맵: virtual_key_id → 마지막으로 쓴 시각
  now - 마지막 쓴 시각 < 60초  →  건너뜀
  그 외                        →  UPDATE (백그라운드 태스크, 실패해도 무시)
```

매 요청 UPDATE하면 인기 키 하나가 초당 수백 번의 row lock을 만듭니다. 이 컬럼의 용도는
"장기 미사용 키 탐지"이므로 분 단위 정확도로 충분합니다. 프로세스마다 독립된 맵이라
pod 수만큼 쓰기가 늘지만, 그래도 요청 수보다는 훨씬 적습니다.

### 인증 실패 기록

```text
outcome ∈ {INVALID_KEY, REVOKED, EXPIRED, OWNER_INACTIVE}
key_hash_prefix = key_hash[:8]      # 원문도 전체 해시도 싣지 않음
```

동일 출처(IP + `key_hash_prefix`)의 연속 실패는 gateway에서 임계까지 집계한 뒤 한 번만
INSERT합니다. 실패마다 쓰면 공격 트래픽이 그대로 DB 부하가 됩니다.

## 테스트 기준

- `ACTIVE` / `ROTATED` 통과, `REVOKED` / `EXPIRED` 거절 — backend의 `can_authenticate()`와
  같은 입력에 같은 답
- `expires_at`이 과거인 `ROTATED` 키 → 거절 (유예 만료)
- 소유자 `is_active=false` → 거절. `TEAM` 소유 키는 팀 비활성으로 거절
- 허용 모델 3층 해석: user 0개 폴백 / team 0개 전체 / VK 교집합 / INACTIVE 제외의 조합을
  테이블 주도로 — backend의 `resolve()`와 결과 일치
- `TEAM` 소유 키의 `user_id`가 NULL로 유지되는지 (usage 이벤트까지)
- `vk:auth` 스냅샷과 인증 쿼리 어디에도 `idp_subject`가 없는지
- 유효 키 두 번째 요청은 DB 왕복 없음
- 캐시 항목이 구버전 형식일 때 → 예외가 아니라 DB 재구성
- backend가 캐시 키를 지운 직후 → 다음 요청에서 DB 재조회
- Redis 장애 / DB 장애 / 동시 장애의 세 조합에서 위 표대로 동작
- `last_used_at`이 60초 내 재요청에서 다시 UPDATE되지 않는지
- 로그·메트릭·에러 응답·`auth_events` 어디에도 키 원문이나 전체 해시가 없음
