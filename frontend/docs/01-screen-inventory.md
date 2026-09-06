# 01. Screen Inventory

| 항목 | 값 |
|---|---|
| 대상 | 콘솔 화면 목록, 역할별 접근, 화면 ↔ Admin API 매핑 |
| 상위 기준 | [00-admin-console-architecture.md](00-admin-console-architecture.md) |

## Scope Boundary

화면 범위는 **backend가 실제로 노출하는 API**가 정합니다. backend 로드맵 기준 M1~M5
(인증·팀·사용자·Virtual Key·모델 카탈로그)가 완료 상태이고, M6~M8(예산·사용량 집계·rate limit)은
미착수입니다.

따라서 예산 화면, 사용량/비용 대시보드, 리더보드, rate limit 설정 화면은 **이 문서에 자리만 두고
구현하지 않습니다.** 없는 API를 목업으로 채우면 나중에 실제 응답과 어긋난 화면을 다시 만들게 됩니다.

## Navigation

```text
┌ 대시보드            /                     운영 점검판
├ 팀                  /teams                /teams/[teamId]
├ 사용자              /users                /users/[userId], /users/tree
├ Virtual Key         /keys                 /keys/[keyId]
├ 모델 카탈로그       /models               /models/[alias]
├ 내 정보             /my
└ 설정                /settings/service-tokens, /settings/cache
```

## Page Permissions

`GET /me`의 role로 판정합니다. 표에 없는 경로는 기본 거부입니다.

| 경로 | ADMIN | TEAM_LEADER | MEMBER |
|---|:---:|:---:|:---:|
| `/` | ✅ | ✅ | — |
| `/teams`, `/teams/[teamId]` | ✅ | ✅ (자기 팀만 열림) | — |
| `/users`, `/users/tree`, `/users/[userId]` | ✅ | ✅ (자기 팀 범위) | — |
| `/keys`, `/keys/[keyId]` | ✅ | ✅ (자기 팀 범위) | — |
| `/models`, `/models/[alias]` | ✅ | ✅ (조회 전용) | — |
| `/my` | — | ✅ | ✅ |
| `/settings/**` | ✅ | — | — |
| `/login`, `/403` | 공개 | 공개 | 공개 |

- `/my`에 ADMIN을 넣지 않습니다. 플랫폼 운영자가 "내 사용량"을 보는 화면은 역할 경계를 흐립니다.
- TEAM_LEADER에게 목록 화면 자체는 열되, 범위 밖 리소스는 backend가 403으로 막습니다.
  화면은 그 403을 "권한 없음"으로 표시하고 존재 여부를 추측하지 않습니다.

## Screens

### `/login` — 로그인

| 항목 | 내용 |
|---|---|
| 소비 API | 없음 (Route Handler가 쿠키만 굽습니다) |
| 동작 | `DEV_LOGIN_ENABLED=true`면 역할 선택 dev 로그인 폼. 아니면 IdP 안내만 |

OIDC IdP가 확정되면 이 화면에 "SSO로 로그인" 버튼이 붙고 `/api/auth/callback`이 추가됩니다.
그 전까지 운영 배포에서는 로그인 수단이 없는 상태가 정상입니다.

### `/` — 대시보드 (운영 점검판)

사용량·비용 지표는 backend M7 이후입니다. 그전까지는 **지금 있는 API로 답할 수 있는 것만**
보여줍니다. 빈 차트 자리를 만들어두지 않습니다.

| 카드 | 소비 API |
|---|---|
| 팀 수 / 사용자 수 | `GET /teams`, `GET /users` |
| 활성 Virtual Key 수 | `GET /virtual-keys?status=ACTIVE` |
| 만료 임박 VK (30일 내) | `GET /virtual-keys?expires_before=...&status=ACTIVE` |
| 오래 안 쓴 VK (90일 이상) | `GET /virtual-keys?unused_since=...&status=ACTIVE` |
| 단가 누락 모델 | `GET /models/missing-pricing` |
| 캐시 무효화 실패 잔량 | `POST /internal/cache/retry` 결과 (ADMIN 전용 카드) |

단가 누락과 캐시 무효화 실패는 **정책이 조용히 어긋나 있는 상태**입니다. 대시보드 첫 화면에
두는 이유가 그것입니다.

### `/teams` — 팀 목록

| 조작 | API |
|---|---|
| 목록 (활성 필터, 커서) | `GET /teams?is_active&cursor&limit` |
| 생성 | `POST /teams` |
| 수정 (이름/설명/활성) | `PATCH /teams/{team_id}` |

### `/teams/[teamId]` — 팀 상세

| 조작 | API |
|---|---|
| 기본 정보 | `GET /teams/{team_id}` |
| 멤버 목록 | `GET /teams/{team_id}/members` |
| 팀장 지정/해제 | `PUT /teams/{team_id}/leader` |
| 허용 모델 조회/설정 | `GET`·`PUT /teams/{team_id}/allowed-models` |
| 팀 VK 일괄 폐기 | `POST /teams/{team_id}/virtual-keys/revoke-all` |

일괄 폐기는 팀 이름을 그대로 입력해야 실행됩니다(`confirm_team_name`). 되돌릴 수 없는 조작이라
확인 다이얼로그를 예/아니오로 끝내지 않습니다.

### `/users` — 사용자 목록

| 조작 | API |
|---|---|
| 목록 (팀·역할·활성·검색, 커서) | `GET /users?team_id&role&is_active&q&cursor&limit` |
| 생성 | `POST /users` |
| 수정 (표시명/역할/활성) | `PATCH /users/{user_id}` |
| 비활성화 | `POST /users/{user_id}/deactivate` |
| 팀 이동 | `PUT /users/{user_id}/team` |

비활성화와 팀 이동은 응답에 `revoked_virtual_keys` / `affected_virtual_keys`와
`cache_invalidated`가 담겨 옵니다. **파급 결과를 결과 화면에 그대로 보여줍니다.**
캐시 무효화가 실패했으면(`cache_invalidated=false`) 경고로 표시하고 `/settings/cache`로 안내합니다.

### `/users/tree` — 조직 트리

`GET /users/tree` 한 번으로 팀-멤버 계층을 그립니다. 팀장은 별도 표시합니다.

### `/users/[userId]` — 사용자 상세

| 조작 | API |
|---|---|
| 기본 정보 | `GET /users/{user_id}` |
| 개인 허용 모델 조회/설정/해제 | `GET`·`PUT`·`DELETE /users/{user_id}/allowed-models` |
| 실효 허용 모델 | `GET /users/{user_id}/effective-models` |
| 소유 VK | `GET /virtual-keys?owner_type=USER&owner_id={user_id}` |

허용 모델은 카탈로그 → 팀 → 사용자 세 층으로 해석됩니다. 화면은 **설정값과 실효값을 나란히**
보여주고, `resolved_from`으로 "지금 어느 층이 이기고 있는지"를 명시합니다.
개인 설정 해제(`DELETE`)와 빈 배열 설정(`PUT []`)은 의미가 다르므로 버튼을 분리합니다.

### `/keys` — Virtual Key 목록

| 조작 | API |
|---|---|
| 목록 (소유자·팀·상태·만료·미사용·검색, 커서) | `GET /virtual-keys?...` |
| 발급 | `POST /virtual-keys` |
| 수정 (이름/허용 모델/만료) | `PATCH /virtual-keys/{key_id}` |
| 로테이션 | `POST /virtual-keys/{key_id}/rotate` |
| 폐기 (사유 필수) | `DELETE /virtual-keys/{key_id}?reason&note` |

발급·로테이션 응답의 `virtual_key`는 **이 순간이 지나면 다시 볼 수 없습니다.** 전용 다이얼로그로
복사 버튼과 함께 한 번 보여주고, 닫으면 메모리에서 사라집니다. 목록·상세 어디에도 남기지 않습니다.

폐기 사유(`reason`)는 감사 요구사항이라 선택 없이 진행할 수 없습니다.

### `/keys/[keyId]` — Virtual Key 상세

| 조작 | API |
|---|---|
| 기본 정보 | `GET /virtual-keys/{key_id}` |
| 감사 이력 + 로테이션 체인 | `GET /virtual-keys/{key_id}/audit` |

로테이션 체인은 이전 키 → 현재 키 순서로 이어 보여줍니다. "누가 언제 왜 이 키를 손댔는가"가
이 화면의 유일한 목적입니다.

### `/models` — 모델 카탈로그

| 조작 | API |
|---|---|
| 목록 (상태 필터) | `GET /models?status` |
| 등록 (초기 단가 필수) | `POST /models` |
| 수정 | `PATCH /models/{alias}` |
| 활성/비활성 전환 | `PATCH /models/{alias}/status` |
| 단가 누락 목록 | `GET /models/missing-pricing` |

모델 등록은 단가를 함께 받습니다. 단가 없는 모델은 사용량이 비용으로 환산되지 않습니다.

### `/models/[alias]` — 모델 상세

| 조작 | API |
|---|---|
| 기본 정보 + 현재 단가 | `GET /models/{alias}` |
| 단가 시계열 | `GET /models/{alias}/pricings` |
| 단가 등록 | `POST /models/{alias}/pricings` |

단가는 구간이 겹치면 backend가 409로 막습니다. 화면은 기존 구간을 시각적으로 보여주어
겹치는 `effective_from`을 애초에 고르기 어렵게 만듭니다. 금액은 문자열 그대로 다룹니다.

### `/my` — 내 정보

| 조작 | API |
|---|---|
| 내 계정 | `GET /me` |
| 내 실효 허용 모델 | `GET /users/{me}/effective-models` |
| 내 소유 VK | `GET /virtual-keys?owner_type=USER&owner_id={me}` |
| 내 키 폐기 | `DELETE /virtual-keys/{key_id}?reason` |

MEMBER는 자기 키를 폐기할 수 있지만 발급할 수는 없습니다(backend 인가 표).

### `/settings/service-tokens` — 서비스 토큰

| 조작 | API |
|---|---|
| 목록 (폐기 포함 토글) | `GET /service-tokens?include_revoked` |
| 발급 | `POST /service-tokens` |
| 로테이션 | `POST /service-tokens/{token_id}/rotate` |
| 폐기 | `DELETE /service-tokens/{token_id}` |

토큰 원문도 VK와 같은 규칙입니다 — 한 번만 보여주고 어디에도 남기지 않습니다.

### `/settings/cache` — 캐시 무효화 재시도

| 조작 | API |
|---|---|
| 미해결 항목 재시도 | `POST /internal/cache/retry` |

control plane은 캐시를 **삭제만** 하고, 실패하면 기록해둡니다. 이 화면은 그 잔량을 사람이
털어내는 곳입니다. 값을 채워 넣는 버튼은 만들지 않습니다 — 채우는 주체는 gateway입니다.

## Deferred Screens

backend 마일스톤이 열려야 착수합니다. 자리만 잡아두고 지금은 만들지 않습니다.

| 화면 | 대기 중인 backend 마일스톤 |
|---|---|
| 예산 설정·소진 현황 | M6 (`backend/docs/05-budget-management.md`) |
| 사용량·비용 대시보드, 리더보드 | M7 (`docs/leaderboard-and-dashboard.md`) |
| rate limit 설정·실시간 사용률 | M8 (`backend/docs/06-rate-limit-management.md`) |
| 감사 로그 전체 조회 | VK 단건 감사 외 목록 API 없음 |
| 모델 비교 playground | 프로젝트 전체 범위 밖 |

## Related Documents

- [00-admin-console-architecture.md](00-admin-console-architecture.md)
- [02-implementation-roadmap.md](02-implementation-roadmap.md)
