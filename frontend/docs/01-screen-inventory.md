# 01. Screen Inventory

| 항목 | 값 |
|---|---|
| 대상 | 콘솔 화면 목록, 역할별 접근, 화면 ↔ Admin API 매핑 |
| 상위 기준 | [00-admin-console-architecture.md](00-admin-console-architecture.md) |

## Scope Boundary

화면 범위는 **backend가 실제로 노출하는 API**가 정합니다. backend 로드맵 기준 M1~M8이
완료되어, 예산·사용량·리더보드·rate limit 화면까지 이 문서의 범위 안에 있습니다.

여전히 같은 규율입니다. **없는 API를 목업으로 채우지 않습니다.** 아래 Deferred Screens에 남은
항목들은 backend에 대응 API가 없어서 만들지 않은 것이고, 자리만 잡아 둡니다.

## Navigation

```text
┌ 대시보드            /                     운영 점검판
├ 팀                  /teams                /teams/[teamId]
├ 사용자              /users                /users/[userId], /users/tree
├ Virtual Key         /keys                 /keys/[keyId]
├ 모델 카탈로그       /models               /models/[alias]
├ 사용량·비용         /usage                필터로 drill-down
├ 예산                /budgets              /budgets/team/[teamId]
├ Rate limit          /rate-limits
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
| `/usage` | ✅ | ✅ (자기 팀 범위) | — |
| `/budgets`, `/budgets/team/[teamId]` | ✅ | ✅ (자기 팀, 배분만) | — |
| `/rate-limits` | ✅ | ✅ (자기 팀 축 + 전역 조회) | — |
| `/my` | — | ✅ | ✅ |
| `/settings/**` | ✅ | — | — |
| `/login`, `/403` | 공개 | 공개 | 공개 |

- `/my`에 ADMIN을 넣지 않습니다. 플랫폼 운영자가 "내 사용량"을 보는 화면은 역할 경계를 흐립니다.
- `/usage`는 backend가 MEMBER에게도 (자기 자신으로 좁혀) 응답하지만, 콘솔에서 MEMBER가 보는
  화면은 `/my` 하나로 유지합니다. 자기 예산은 거기에 있습니다.
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

| 카드 | 소비 API |
|---|---|
| 팀 수 / 사용자 수 | `GET /teams`, `GET /users` |
| 활성 Virtual Key 수 | `GET /virtual-keys?status=ACTIVE` |
| 만료 임박 VK (30일 내) | `GET /virtual-keys?expires_before=...&status=ACTIVE` |
| 오래 안 쓴 VK (90일 이상) | `GET /virtual-keys?unused_since=...&status=ACTIVE` |
| 단가 누락 모델 | `GET /models/missing-pricing` |
| 최근 30일 비용·호출·실패율 | `GET /usage/overview` |
| 정책 거절 건수 | `GET /usage/auth-events` |
| 예산 경보 중인 팀 | `GET /budgets/summary?scope=TEAM` |
| 예산 없는 팀 | `GET /budgets/unset` (ADMIN 전용 카드) |
| 캐시 무효화 실패 잔량 | `POST /internal/cache/retry` 결과 (ADMIN 전용 카드) |

지표가 늘어도 첫 화면의 초점은 그대로 **정책이 조용히 어긋나 있는 상태**입니다. 비용 총액보다
실패율·예산 경보·예산 미설정·단가 누락이 먼저 보여야 합니다. 미설정 예산은 경보가 뜨지 않으므로
이 카드가 유일한 노출 경로입니다.

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
| 이 키의 한도와 실효 한도 | `GET /rate-limits?scope=VIRTUAL_KEY`, `GET /rate-limits/effective` |

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

### `/usage` — 사용량·비용

| 조작 | API |
|---|---|
| 합계 + 상위 팀/사용자/모델 | `GET /usage/overview` |
| 축 × 지표 리더보드 | `GET /usage/leaderboard?axis&metric&limit` |
| 기간별 추이 (일/월) | `GET /usage/trend?granularity` |
| 정책 거절 요약 | `GET /usage/auth-events` |

네 조회가 **같은 필터**(`from_date`, `to_date`, `team_id`, `user_id`, `virtual_key_id`,
`model_alias`)를 씁니다. drill-down은 별도 화면이 아니라 리더보드 행이 자기 축의 필터를 URL에
붙이는 것이고, 그러면 합계·추이까지 같은 조건으로 좁혀집니다. 숫자가 서로 다른 기준에서 나오지
않게 하는 것이 이 구조의 목적입니다.

기간은 UTC 일자이고 **양끝을 포함**합니다. 상한 366일을 넘기거나 형식이 깨진 값은 화면이 기본
기간(최근 30일)으로 되돌립니다. 값이 없는 버킷은 응답에 행이 없고, 화면이 기간을 알고 채웁니다 —
**0으로 채우지 않습니다.** "집계가 아직 안 돈 날"과 "호출이 없던 날"은 다릅니다.

정책 거절은 `occurrence_count`가 실제 실패 수입니다. gateway가 연속 실패를 60초 창으로 묶으므로
행 수(`event_rows`)로 세면 과소 계상됩니다. 둘 다 보여주되 앞의 것을 대표값으로 씁니다.

### `/budgets` — 예산 소진 현황

| 조작 | API |
|---|---|
| 기간·scope별 소진 요약 | `GET /budgets/summary?scope&period` |
| 예산 미설정 목록 | `GET /budgets/unset` (ADMIN) |

**미설정은 무제한입니다.** 경보가 뜨지 않으므로 상시 노출이 유일한 방어선이고, 그래서 소진
목록과 같은 화면에 둡니다. 소진값의 출처(Redis 집행 카운터 / DB 집계)도 숨기지 않습니다 —
둘이 갈라진 상태를 알아야 재시드가 필요한지 판단할 수 있습니다.

### `/budgets/team/[teamId]` — 팀 예산

| 조작 | API |
|---|---|
| 소진 상세 + 멤버·모델 breakdown | `GET /budgets/team/{team_id}/usage?period` |
| 배분 현황 | `GET /budgets/team/{team_id}/allocation?period` |
| 예산 설정·해제 | `PUT`·`DELETE /budgets/team/{team_id}` (ADMIN) |
| 배분 일괄 설정 | `PUT /budgets/team/{team_id}/allocation` |
| 소진값 재시드 | `PUT /budgets/usages/reseed` (ADMIN) |

세 가지를 화면이 구분해서 말해야 합니다.

- **예산 해제(무제한)와 한도 0(쓸 수 없음)** — 버튼과 문구를 분리합니다.
- **배분은 전체 교체** — 빈 칸으로 두면 그 멤버의 배분이 해제됩니다. 합계는 화면이 미리 더해
  보여주지만 판정은 backend(409 `allocation_exceeds_team_budget`)가 합니다.
- **재시드는 운영 예외** — control plane이 집행 카운터를 쓰는 유일한 경로라 사유가 필수이고
  감사에 before/after가 남습니다. 일반 저장 버튼처럼 보이지 않게 위험 버튼으로 둡니다.

한도 설정은 ADMIN, 배분은 팀장까지입니다. 팀장에게 한도 입력칸을 보여주고 403을 받게 하지
않습니다.

### `/rate-limits` — Rate limit

| 조작 | API |
|---|---|
| 전역·주체 설정 목록 | `GET /rate-limits?scope&scope_id&model_alias` |
| 팀 → 멤버 트리와 실효값 | `GET /rate-limits/tree?team_id&model_alias` |
| 설정·해제 | `PUT`·`DELETE /rate-limits/{scope}/...` |
| 실시간 사용률 | `GET /rate-limits/usage` |

두 축을 **따로** 그립니다. 주체 축(VK > 사용자 > 팀)과 전역 축(모델별 GLOBAL)은 둘 다 통과해야
요청이 진행되므로, 한 표에 섞으면 "어느 쪽에서 막혔는가"를 설명할 수 없습니다.

폴백은 **한도 종류별로 독립**입니다. 사용자가 tpm만 정의했다면 rpm은 팀에서 옵니다. 트리의
실효값 칸이 종류별로 다른 층을 가리키는 것이 정상이고, `resolved_from`이 그 층을 밝힙니다.

빈 칸(`null` 저장)과 해제(`DELETE`)는 다릅니다 — 앞은 "이 층에서 정의하지 않음", 뒤는 정의
자체를 없애는 것입니다. 버튼을 분리합니다. 상위보다 큰 하위 설정이 남으면 backend가 거절하지
않고 `conflicting_children`으로 알려 주며, 화면은 그것을 저장 직후에 그대로 띄우고 자동으로
깎지 않습니다.

실시간 사용률은 best-effort입니다. gateway 집행 카운터 키 규약이 확정되기 전에는
`available=false`이고, **그것은 오류가 아니라 정상 상태**입니다. 관측이 안 된다고 설정 화면이
멈추지 않습니다.

### `/my` — 내 정보

| 조작 | API |
|---|---|
| 내 계정 | `GET /me` |
| 내 예산과 소진 | `GET /me/budget` |
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
| 감사 로그 전체 조회 | VK 단건 감사 외 목록 API 없음 |
| 모델 비교 playground | 프로젝트 전체 범위 밖 |

## Related Documents

- [00-admin-console-architecture.md](00-admin-console-architecture.md)
- [02-implementation-roadmap.md](02-implementation-roadmap.md)
