# 00. Admin Console Architecture

| 항목 | 값 |
|---|---|
| 대상 | `frontend/` (control plane, Admin Console) |
| 브랜치 | `feat/admin-frontend` |
| 상위 기준 | [AGENTS.md](../../AGENTS.md), [docs/implementation-plan.md](../../docs/implementation-plan.md) |
| 계약 원천 | `backend/`가 생성하는 OpenAPI 문서 |
| 참조 구현 | `awsome-ai-gateway/admin-ui` |

## Objective

Admin Console은 Admin API를 사람이 조작하는 유일한 화면입니다. 자체 정책 판단을 하지 않고,
**backend의 판정을 그대로 비춥니다.** 화면에서 버튼을 숨기는 것은 편의이지 통제가 아니며,
통제는 항상 backend의 403이 합니다.

이 문서는 경계, 레이어, 세션/인가, 데이터 페칭·에러·표시 규약을 정의합니다.
화면 목록은 [01](01-screen-inventory.md), 구현 순서는 [02](02-implementation-roadmap.md)입니다.

## Service Boundary

```text
Admin (browser)
   │   Cookie: admin_session (httpOnly, SameSite=Lax)
   ▼
frontend (Next.js App Router, SSR)
   ├─ Server Component  → fetch(Admin API)   조회
   ├─ Server Action     → fetch(Admin API)   변경 + revalidatePath
   └─ Route Handler     → 세션 쿠키 발급/파기 (로그인·로그아웃)
   │   Authorization: Bearer <session token>
   ▼
backend (Admin API)
```

경계 규칙:

- **브라우저는 backend를 직접 호출하지 않습니다.** 모든 호출은 Server Component, Server Action,
  Route Handler 중 하나를 경유합니다. `ADMIN_API_URL`은 서버 전용 환경변수이고
  `NEXT_PUBLIC_` 접두사를 쓰지 않습니다.
- **세션 토큰은 클라이언트 번들에 절대 들어가지 않습니다.** httpOnly 쿠키로만 다루고,
  Server Component의 props로 토큰을 내려보내지 않습니다.
- frontend는 gateway(data plane)를 호출하지 않습니다. Virtual Key 원문은 발급 응답을
  화면에 1회 보여줄 뿐, 저장하거나 재조회하지 않습니다.
- frontend는 PostgreSQL과 Redis에 접근하지 않습니다.

## Layering

```text
src/
├── app/                    라우트. Server Component 가 기본, 'use client' 는 예외
│   ├── (console)/          인증된 콘솔 레이아웃(사이드바 + 헤더)
│   ├── login/              세션이 없는 상태에서만 들어오는 화면
│   └── api/auth/           세션 쿠키를 굽고 파기하는 Route Handler
├── components/
│   ├── ui/                 도메인을 모르는 프리미티브 (Button, Table, Dialog, Badge …)
│   └── <domain>/           도메인 컴포넌트 (teams, users, keys, models …)
├── lib/
│   ├── api/                Admin API 클라이언트와 도메인별 조회 함수
│   ├── actions/            Server Action ('use server')
│   ├── auth/               세션 읽기, 역할 판정, 페이지 권한표
│   └── format/             날짜·금액·상태 표시 변환
└── types/                  OpenAPI 계약을 옮긴 타입
```

규칙:

- **조회는 Server Component가, 변경은 Server Action이 합니다.** 클라이언트 컴포넌트가
  `fetch`로 데이터를 직접 가져오지 않습니다.
- `'use client'`는 상호작용이 필요한 잎 컴포넌트에만 붙입니다. 페이지 전체를 클라이언트로
  만들지 않습니다.
- `lib/api/`는 HTTP와 타입 변환만 알고, 도메인 규칙을 갖지 않습니다.
- `components/ui/`는 도메인 타입을 import하지 않습니다. 재사용 경계가 무너지는 신호입니다.

## Session and Authentication

backend는 네 갈래 인증 경로를 가집니다(dev 토큰 / 서비스 토큰 / OIDC / Admin JWT).
**frontend는 그중 어느 것도 검증하지 않습니다.** 토큰을 쿠키에 담아 전달만 하고,
유효성 판단은 전부 backend가 합니다.

```text
로그인 경로 (교체 가능한 지점)
  ├─ dev  : POST /api/auth/dev-login   → dev.<base64url(payload)>.<sig> 를 굽는다
  └─ OIDC : GET  /api/auth/callback    → IdP 가 준 id_token 을 그대로 굽는다 (IdP 확정 후)
                    │
                    ▼
        Cookie: admin_session (httpOnly, SameSite=Lax, Secure=요청 scheme 기준)
                    │
                    ▼
        모든 서버측 호출에 Authorization: Bearer <쿠키값>
```

- 쿠키 이름은 backend의 `SESSION_COOKIE_NAME`과 같은 `admin_session`입니다. 이름을 맞춰두면
  같은 브라우저에서 backend를 직접 열어 디버깅할 때 그대로 통합니다.
- dev 로그인은 `DEV_LOGIN_ENABLED=true`일 때만 열리고, 아니면 라우트가 404를 냅니다.
  backend도 같은 이름의 설정으로 같은 경로를 열고 닫으므로 **두 값을 항상 함께 맞춥니다.**
- OIDC 도입 시 추가되는 것은 `/api/auth/callback` 하나입니다. 이후 경로(쿠키 → Bearer)는
  바뀌지 않습니다. IdP 확정은 backend 07 문서의 미결정 #1입니다.
- 로그아웃은 쿠키를 지우는 것뿐입니다. backend에 세션 저장소가 없어 서버측 무효화가 없습니다.

## Authorization

**역할의 원천은 `GET /api/v1/me`입니다. 토큰 payload가 아닙니다.**

backend는 역할을 DB(`auth.users.role`)와 부트스트랩 설정(`ADMIN_EMAILS`/`ADMIN_GROUPS`)으로
판정합니다. IdP가 주는 id_token에는 우리 역할 개념이 없을 수 있으므로, 토큰을 뜯어 역할을
읽으면 화면과 backend의 판정이 갈립니다.

> 참조 구현과의 차이: 참조 admin-ui는 JWT payload의 `role` claim을 파싱해 미들웨어에서
> 인가까지 끝냅니다. 우리 backend는 role을 claim으로 내보내지 않으므로 그 방식을 쓸 수 없습니다.

그래서 판정을 두 층으로 나눕니다.

| 층 | 위치 | 판정 | 실패 시 |
|---|---|---|---|
| 인증 게이트 | `middleware.ts` | 세션 쿠키 유무만 | `/login` 리다이렉트 |
| 역할 인가 | 콘솔 레이아웃 / 페이지 | `GET /me`의 role + 페이지 권한표 | `/403` |

- 미들웨어에서 `GET /me`를 호출하지 않습니다. 정적 자산까지 포함한 모든 요청에 API 왕복이
  붙습니다. 콘솔 레이아웃에서 한 번 호출하고 React `cache()`로 요청 단위 중복을 제거합니다.
- 화면의 역할 게이팅은 **노이즈 제거**입니다. 권한 없는 버튼을 감추더라도, 그 조작을 막는 것은
  backend의 403입니다. 화면 조건문을 통제 수단으로 쓰지 않습니다.
- `TEAM_LEADER`가 다른 팀 리소스를 열면 backend가 404가 아니라 403을 줍니다(백엔드 00 문서).
  화면은 이 둘을 다른 문구로 구분해 보여줍니다.

## Data Fetching

- 조회는 전부 `cache: 'no-store'`입니다. 정책 콘솔에서 오래된 값을 보여주는 것은 버그입니다.
- 변경 성공 후 `revalidatePath`로 관련 경로를 무효화합니다. 낙관적 업데이트는 쓰지 않습니다.
  실제로 반영됐는지를 backend 응답으로 확인하는 편이 정책 화면에 맞습니다.
- 목록은 backend와 같은 **cursor 페이지네이션**입니다. offset을 만들어내지 않습니다.

  ```json
  {"items": [...], "next_cursor": "...", "has_more": true}
  ```

  커서는 URL의 `?cursor=`로 관리해 SSR과 새로고침에서 동일한 화면이 나오게 합니다.
  "이전 페이지"는 방문한 커서를 URL에 쌓아 구현하고, 페이지 번호는 만들지 않습니다.
- 필터도 URL searchParams가 원천입니다. 컴포넌트 상태에 필터를 두면 공유·새로고침에서 깨집니다.
- 재시도는 조회(GET)에만 겁니다. 변경 요청은 재시도하지 않습니다 — VK 발급·로테이션이
  멱등하지 않아 중복 발급이 생깁니다.

## Error Contract

backend의 실패 응답은 하나의 봉투를 씁니다. frontend는 **`code`로 분기하고 `message`를 보여줍니다.**

```json
{"error": {"code": "duplicate_alias", "message": "...", "details": {...}, "request_id": "0f9c..."}}
```

- `lib/api/`는 실패를 `AdminApiError(status, code, message, details, requestId)`로 바꿔 던집니다.
  화면은 상태 코드가 아니라 `code`를 봅니다.
- Server Action은 예외를 밖으로 던지지 않고 `ActionResult`로 감쌉니다.
  던지면 Next가 프로덕션에서 메시지를 지워버려 사용자에게 원인을 전달할 수 없습니다.

  ```ts
  type ActionResult<T = void> =
    | { ok: true; data: T }
    | { ok: false; code: string; message: string; fieldErrors?: Record<string, string> };
  ```

- 422(FastAPI 검증 실패)는 필드 단위 오류로 풀어 폼에 붙입니다.
- `request_id`는 오류 표시에 항상 함께 보여줍니다. 이것 하나로 backend 로그를 찾을 수 있습니다.
- **비밀값을 오류 메시지에 담지 않습니다.** VK 원문과 서비스 토큰 원문은 로그·토스트·URL에
  들어가지 않습니다.

## Display Conventions

backend의 직렬화 규약을 화면이 깨뜨리지 않게 고정합니다.

| 대상 | 규약 |
|---|---|
| 금액 | backend가 **문자열**로 줍니다. `Number()`로 바꾸지 않고 문자열 상태로 자릿수만 다듬습니다 |
| 시간 | 응답은 ISO-8601 UTC. 화면은 KST로 변환해 `YYYY-MM-DD HH:mm` 형태로 보여줍니다 |
| ID | UUID는 등폭 글꼴로, 목록에서는 앞 8자만 보여주고 전체는 복사 버튼으로 제공합니다 |
| VK 원문 | 발급·로테이션 응답에서 **단 한 번** 보여줍니다. 재조회 수단을 만들지 않습니다 |
| 상태 | `ACTIVE`/`REVOKED` 같은 enum은 한국어 라벨과 색으로 매핑해 표 전체에서 통일합니다 |

금액을 float으로 바꾸는 순간 `0.0003` 같은 단가에서 정밀도가 깨집니다. AGENTS.md의 공통 규약이
프론트에서 무너지는 지점이라 규칙으로 못박습니다.

## UI Baseline

| 항목 | 선택 | 근거 |
|---|---|---|
| 프레임워크 | Next.js 15 (App Router) + React 19 | SSR 유지. 신규 프로젝트라 마이그레이션 부채 없음 |
| 언어 | TypeScript strict | 계약 타입을 컴파일 타임에 강제 |
| 스타일 | Tailwind CSS + CSS 변수 토큰 | 라이트/다크를 토큰 한 곳에서 전환 |
| 프리미티브 | Radix UI (Dialog, Select, Toast 등) | 포커스 트랩·키보드 내비게이션을 직접 만들지 않음 |
| 언어 표기 | 한국어 단일 | 사내 콘솔. i18n 라이브러리를 두지 않음 |

- 색·간격·모서리는 CSS 변수로만 정의하고 컴포넌트에 하드코딩하지 않습니다.
- 순백/순흑 대신 토큰을 씁니다. 다크 모드에서 대비가 깨지는 가장 흔한 원인입니다.
- 아이콘은 `lucide-react` 하나로 통일합니다.

## Configuration

| 변수 | 필수 | 설명 |
|---|---|---|
| `ADMIN_API_URL` | 예 | Admin API 베이스 URL. 서버 전용 |
| `DEV_LOGIN_ENABLED` | 아니오 | `true`일 때만 dev 로그인 라우트가 열립니다. backend와 값을 맞춥니다 |
| `DEV_LOGIN_USER_ID` | 아니오 | dev 토큰에 담을 사용자 UUID. 비우면 backend의 합성 주체를 씁니다 |
| `SESSION_COOKIE_SECURE` | 아니오 | 강제 지정용. 비우면 요청 scheme으로 판단합니다 |

- `NEXT_PUBLIC_` 접두사 변수는 두지 않습니다. 콘솔이 브라우저에서 알아야 할 설정이 없습니다.
- 필수 설정이 없으면 조용히 기본값으로 뜨지 않고 첫 API 호출에서 명확한 오류를 냅니다.

## Observability

- `GET /api/health` — 컨테이너 헬스체크용. backend를 건드리지 않고 프로세스 생존만 확인합니다.
- 서버 로그에 `x-request-id`를 함께 남깁니다. backend가 응답 헤더로 돌려주는 값을 그대로 씁니다.
- 세션 토큰, VK 원문, 서비스 토큰 원문은 로그에 남기지 않습니다.

## 참조 구현과의 차이 (요약)

| 항목 | 참조 구현 | 이 프로젝트 | 근거 |
|---|---|---|---|
| 역할 판정 | 미들웨어에서 JWT payload 파싱 | `GET /me` 응답 | 우리 backend는 role을 claim으로 내보내지 않음 |
| i18n | next-intl ko/en | 한국어 단일 | 사내 콘솔. 번역 누락 관리 비용이 이득보다 큼 |
| 챗 어시스턴트 | `admin-chat-agent` 연동 화면 | 구현하지 않음 | 프로젝트 범위 밖(backend 07 문서와 동일) |
| 생산성/ROI 화면 | 코드 수락률 등 제품 특화 지표 | 구현하지 않음 | 우리 usage 이벤트에 해당 축이 없음 |
| 관측 | OpenTelemetry SDK 내장 | 구조적 로그만 | 배포 표준이 정해진 뒤 도입 |

## Related Documents

- [01-screen-inventory.md](01-screen-inventory.md) — 화면 목록, 역할별 접근, 소비 API
- [02-implementation-roadmap.md](02-implementation-roadmap.md) — 마일스톤과 미결정
- `backend/docs/00-admin-api-architecture.md` — 인가 표, 에러 봉투, API 규약의 원천
