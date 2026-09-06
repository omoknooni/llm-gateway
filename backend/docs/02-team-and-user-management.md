# 02. Team and User Management

| 항목 | 값 |
|---|---|
| 대상 | 팀/사용자 CRUD, 역할 부여, 팀 이동 |
| 상위 기준 | [00](00-admin-api-architecture.md), [01](01-data-model.md) |
| 관련 문서 | [docs/virtual-key-management.md](../../docs/virtual-key-management.md) |

## Objective

팀과 사용자는 이 플랫폼의 **정책 부착점**입니다. 예산, rate limit, 허용 모델, VK 소유권,
사용량 집계가 모두 팀/사용자 축에 붙습니다. 따라서 이 도메인의 정확성이 나머지 전부의 전제입니다.

## Scope

- 팀 CRUD, 팀장 지정
- 사용자 CRUD, 역할 부여, 활성/비활성
- 사용자 팀 이동과 그 파급
- 조직 트리 조회(frontend 화면용)

범위 밖: SSO 프로비저닝 자동화(Phase 4+), 부서 계층.

## Entity Rules

### 팀

- `name`은 유일합니다. 중복 생성 시 409 `duplicate_team_name`.
- 팀 삭제는 hard delete하지 않습니다. `is_active=false`로 비활성화합니다.
  비활성 팀은 새 사용자 배정과 새 VK 발급의 대상이 될 수 없고, 기존 사용량 이력은 남습니다.
- 활성 멤버가 있는 팀은 비활성화할 수 없습니다. 409 `team_has_active_members`.
- `leader_user_id`는 그 팀 소속 사용자여야 합니다. 다른 팀 사용자를 팀장으로 지정하면
  400 `leader_not_in_team`.

### 사용자

- `email`이 유일 식별자입니다. 대소문자를 구분하지 않습니다(citext).
- OIDC 로그인 주체는 `idp_subject`로 기존 사용자와 연결됩니다. 미등록 주체의 자동 생성(JIT
  프로비저닝)은 그룹 → 팀 매핑 규칙이 확정된 뒤에 켭니다. 그 전까지는 관리자가 먼저 생성하고,
  첫 로그인 시 `idp_subject`와 `provider`가 채워집니다.
- `role`은 `ADMIN` / `TEAM_LEADER` / `MEMBER`입니다. `TEAM_LEADER` 역할과
  `teams.leader_user_id`는 **별개**입니다. 역할은 권한, 팀장 지정은 소속 관계입니다.
  둘의 정합성은 서비스가 맞춥니다: 팀장으로 지정하면 역할이 `MEMBER`인 경우 `TEAM_LEADER`로 승격하고,
  팀장에서 해제해도 역할은 자동으로 내리지 않습니다(다른 팀의 팀장일 수 있음 — 감사 로그에 남깁니다).
- 마지막 남은 활성 `ADMIN`의 역할 강등과 비활성화는 거절합니다. 409 `last_admin_protected`.
  관리자가 0명이 되면 복구 경로가 부트스트랩 재실행뿐이기 때문입니다.
- 사용자 비활성화(`is_active=false`)는 **논리적 오프보딩**입니다. 아래 파급이 따릅니다.

## Cascade Rules

상태 변경이 다른 도메인에 미치는 영향을 명시합니다. 여기가 틀리면 폐기된 사람의 키가 살아남습니다.

| 조작 | 파급 |
|---|---|
| 사용자 비활성화 | 소유 VK 전부 `REVOKED`(사유 `USER_DEACTIVATED`) → 각 VK 캐시 키 삭제 → 감사 기록 |
| 사용자 팀 이동 | `virtual_keys.team_id` 갱신 → 해당 VK 캐시 키 삭제 → 사용자 예산/rate limit 설정 유지, 팀 상속분은 새 팀 기준으로 재해석 |
| 사용자 삭제 요청 | 지원하지 않음. 비활성화로 처리(사용량 이력의 FK 무결성) |
| 팀 비활성화 | 활성 멤버가 없어야 하므로 VK 파급 없음. 팀 예산·rate limit 설정은 `is_active=false` |
| 팀장 변경 | 권한 변화만. VK·예산 영향 없음 |

### 팀 이동의 처리 원칙

사용자가 팀을 옮기면 **과거 사용량은 옛 팀에 남고, 이후 사용량은 새 팀에 쌓입니다.**
`usage_events`에 기록 시점의 `team_id`가 이미 박혀 있으므로 소급 재작성하지 않습니다.
"팀별 월 비용"이 이동 시점을 기준으로 갈리는 것은 의도된 동작이며, 대시보드에 그렇게 설명합니다.

팀 이동은 VK를 폐기하지 않습니다. VK는 사람에 귀속되고 팀은 그 사람의 속성이기 때문입니다.
다만 gateway가 캐시에 들고 있는 인증 컨텍스트에 옛 `team_id`가 들어 있으므로,
**이동 트랜잭션 커밋 직후 해당 사용자 소유 VK 전부의 캐시 키를 삭제**합니다. 이 삭제가 빠지면
새 팀의 예산·rate limit이 캐시 TTL만큼 늦게 적용됩니다.

즉시 차단이 필요한 상황(보안 사고, 오프보딩)은 팀 이동이 아니라 **비활성화 또는 VK 일괄 폐기**로
처리합니다. 03 문서에 팀 단위 일괄 폐기 API를 둡니다.

## API

베이스 경로는 `/api/v1`입니다.

### 팀

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `POST` | `/teams` | ADMIN | 팀 생성 |
| `GET` | `/teams` | ADMIN / TEAM_LEADER(자기 팀) | 목록. `?is_active=&cursor=&limit=` |
| `GET` | `/teams/{team_id}` | ADMIN / 소속 | 단건 |
| `PATCH` | `/teams/{team_id}` | ADMIN | 이름·설명·활성 상태 |
| `PUT` | `/teams/{team_id}/leader` | ADMIN | 팀장 지정/해제 |
| `GET` | `/teams/{team_id}/members` | ADMIN / 팀장 | 멤버 목록 |

### 사용자

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `POST` | `/users` | ADMIN | 사용자 생성 |
| `GET` | `/users` | ADMIN / TEAM_LEADER(자기 팀) | 목록. `?team_id=&role=&is_active=&q=` |
| `GET` | `/users/{user_id}` | ADMIN / 팀장 / 본인 | 단건 |
| `PATCH` | `/users/{user_id}` | ADMIN | 표시명·역할·활성 상태 |
| `PUT` | `/users/{user_id}/team` | ADMIN | 팀 이동(팀 해제는 `null`) |
| `GET` | `/me` | 인증된 전원 | 내 프로필·역할·팀 |

### 조직 트리

| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| `GET` | `/org/tree` | ADMIN / TEAM_LEADER | 팀 → 멤버 트리. 각 노드에 정책 설정 여부 플래그 포함 |

`/org/tree`는 화면 전용 집계 엔드포인트입니다. 팀 수 × 멤버 수가 커지면 N+1이 되기 쉬우므로
2회 쿼리(팀 전체 + 멤버 전체)로 메모리에서 조립합니다.

### 요청/응답 예시

```http
PUT /api/v1/users/{user_id}/team
{"team_id": "9f2c...", "reason": "조직 개편"}
```

```json
{
  "user_id": "3a1e...",
  "team_id": "9f2c...",
  "previous_team_id": "77bd...",
  "affected_virtual_keys": 3,
  "cache_invalidated": true
}
```

`affected_virtual_keys`와 `cache_invalidated`를 응답에 넣습니다. 운영자가 "정책이 언제 반영되는가"를
화면에서 바로 알 수 있어야 하고, 무효화 실패 시 그 사실이 조용히 묻히면 안 되기 때문입니다.

## Transaction and Ordering

팀 이동을 예로 든 표준 순서입니다. 모든 파급 있는 조작이 이 순서를 따릅니다.

1. 트랜잭션 시작
2. 대상 행 `SELECT ... FOR UPDATE` (동시 수정 방지)
3. 검증 (소유권, 상태 전이, 상한)
4. 업무 데이터 변경
5. 감사 로그 INSERT (같은 트랜잭션)
6. **커밋**
7. 캐시 키 삭제 (실패 시 `audit.cache_invalidation_failures` 기록, 요청은 성공 응답)

커밋 전에 캐시를 지우면, 커밋 사이에 들어온 gateway 요청이 **옛 값을 다시 캐시에 채웁니다.**
반대 순서를 허용하지 않습니다.

## Validation

- 이메일 형식 검증 + 사내 도메인 허용 목록(설정값, 비어 있으면 검사 안 함).
- 표시명은 1~255자, 앞뒤 공백 제거.
- 팀 이름은 1~255자, 공백만으로 구성 불가.
- 역할 변경은 자기 자신에게 적용할 수 없습니다(권한 상실 자해 방지). 409 `cannot_modify_self_role`.

## Audit Events

| action | resource_type | changes |
|---|---|---|
| `CREATE_TEAM` / `UPDATE_TEAM` / `DEACTIVATE_TEAM` | `team` | before/after |
| `SET_TEAM_LEADER` | `team` | 이전/신규 팀장 |
| `CREATE_USER` / `UPDATE_USER` | `user` | before/after (비밀번호 해시 제외) |
| `DEACTIVATE_USER` | `user` | 폐기된 VK 개수 포함 |
| `TRANSFER_USER_TEAM` | `user` | 이전/신규 팀, 사유 |
| `GRANT_ROLE` | `user` | 이전/신규 역할 |

## 참조 구현과의 차이

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| 조직 계층 | organization → department → team | team 단일 계층 | 요구된 집계 축에 부서가 없습니다. 근거 없는 계층은 인가·예산 배분만 복잡하게 만듭니다 |
| 사용자 프로비저닝 | Cognito group sync가 자동 생성·팀 배정 | 관리자가 생성, 첫 로그인 시 `idp_subject` 연결 | 인증 방식은 동일하나 사내 IdP와 그룹 → 팀 매핑이 미확정입니다. 확정 후 JIT 프로비저닝을 켭니다 |
| 팀 이동 시 VK | 강제 재인증(전원 VK 폐기) 옵션 제공 | 폐기하지 않고 캐시만 무효화 | 우리 VK는 장기 키라 폐기하면 client가 즉시 깨집니다. 즉시 차단은 별도 API로 분리(03) |
| 역할 | ADMIN / TEAM_LEADER / DEVELOPER | ADMIN / TEAM_LEADER / MEMBER | 이 플랫폼 사용자가 개발자로 한정되지 않습니다 |

## 미결정

- 부서 계층 도입 여부. 예산 롤업 요구가 생기면 `teams.parent_team_id`로 확장합니다.
- 그룹 → 팀 매핑 규칙과 JIT 프로비저닝 활성화 시점. 사내 IdP 확정과 함께 정합니다(07 미결정 #1).
