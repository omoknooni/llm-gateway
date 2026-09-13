# frontend — Admin Console (control plane)

Admin 서비스의 웹 콘솔. Next.js SSR 앱으로 동작하며 `backend/`의 Admin API만 소비합니다.
**브라우저는 Admin API를 직접 호출하지 않고** SSR 서버, Server Action, Route Handler를 경유합니다.

- 스택: Next.js 15 (App Router) + React 19 + TypeScript, Tailwind CSS v4, Radix UI
- 작업 브랜치: `feat/admin-frontend`
- 기준 문서: [docs/00-admin-console-architecture.md](docs/00-admin-console-architecture.md)

## 구현 범위

backend 로드맵 M1~M8(인증·팀·사용자·Virtual Key·모델 카탈로그·예산·사용량 집계·rate limit)에
대응하는 화면이 구현되어 있습니다. 화면별 소비 API와 역할별 접근 권한은
[docs/01-screen-inventory.md](docs/01-screen-inventory.md)에 있습니다.

| 경로 | 내용 |
|---|---|
| `/` | 운영 점검판 — 만료 임박 키, 유휴 키, 단가 누락 모델, 최근 사용량, 예산 경보 |
| `/teams`, `/teams/[teamId]` | 팀 CRUD, 팀장 지정, 팀 허용 모델, VK 일괄 폐기 |
| `/users`, `/users/tree`, `/users/[userId]` | 사용자 CRUD, 팀 이동, 조직 트리, 개인 허용 모델과 실효 모델 |
| `/keys`, `/keys/[keyId]` | VK 발급·수정·로테이션·폐기, 감사 이력과 로테이션 체인 |
| `/models`, `/models/[alias]` | 모델 카탈로그, 상태 전환, 단가 시계열 |
| `/usage` | 사용량·비용 합계와 추이, 축별 리더보드, 정책 거절 요약 |
| `/budgets`, `/budgets/team/[teamId]` | 예산 소진 현황, 미설정 목록, 팀 예산·멤버 배분, 소진값 재시드 |
| `/rate-limits` | 전역·팀·사용자 한도 설정, 실효값 해석, 실시간 사용률 |
| `/my` | 내 계정, 내 예산, 내 실효 허용 모델, 내 키 |
| `/settings/service-tokens`, `/settings/cache` | 서비스 토큰, 캐시 무효화 재시도 |

## 실행

```bash
cd frontend
cp .env.example .env
npm install
npm run dev            # http://localhost:3000
```

`ADMIN_API_URL`이 가리키는 Admin API가 떠 있어야 화면이 채워집니다. backend 실행 방법은
`backend/README.md`에 있습니다.

| 스크립트 | 내용 |
|---|---|
| `npm run dev` | 개발 서버 |
| `npm run build` / `npm start` | 프로덕션 빌드와 실행 |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |
| `npm test` | vitest 단위 테스트 |

## 로그인

운영 경로는 사내 SSO(OIDC)이고 IdP는 아직 확정되지 않았습니다(backend `docs/07` 미결정 #1).
지금 열려 있는 것은 **개발용 로그인**뿐입니다.

```bash
# frontend/.env 와 backend/.env 양쪽에 같은 값으로 둡니다.
DEV_LOGIN_ENABLED=true
```

한쪽만 켜면 토큰은 구워지지만 모든 API 호출이 401이 됩니다. 실제 사용자 소유 리소스를
다루려면 `DEV_LOGIN_USER_ID`에 `auth.users.id`를 넣으세요. 비우면 backend의 합성 주체로
들어가고, 그 주체는 소유한 리소스가 없습니다.

`DEV_LOGIN_ENABLED`가 꺼진 배포에서는 로그인 수단이 없는 것이 **정상 상태**입니다.
IdP가 확정되면 `/api/auth/callback` 하나가 추가되고, 이후 경로(쿠키 → Bearer)는 그대로입니다.

## 설정

| 변수 | 필수 | 설명 |
|---|---|---|
| `ADMIN_API_URL` | 예 | Admin API 베이스 URL. **서버 전용** |
| `DEV_LOGIN_ENABLED` | 아니오 | 개발용 로그인 라우트 개폐. backend와 값을 맞춥니다 |
| `DEV_LOGIN_USER_ID` | 아니오 | dev 토큰에 담을 사용자 UUID |
| `SESSION_COOKIE_SECURE` | 아니오 | 세션 쿠키 Secure 강제. 비우면 요청 scheme으로 판단 |

`NEXT_PUBLIC_` 접두사 변수는 두지 않습니다. 콘솔이 브라우저에서 알아야 할 설정이 없습니다.

## 알아둘 규약

이 셋은 어기면 조용히 잘못된 화면이 됩니다.

- **금액은 문자열입니다.** backend가 `Decimal`을 문자열로 직렬화합니다. `Number()`로 바꾸면
  `0.0003` 같은 단가의 정밀도가 깨집니다. 표시는 `lib/format/decimal.ts`를 씁니다.
- **역할의 원천은 `GET /api/v1/me`입니다.** 토큰 payload를 뜯어 역할을 읽지 않습니다.
  backend는 역할을 DB로 판정하며 claim으로 내보내지 않습니다.
- **원문 비밀값은 한 번만 보입니다.** VK와 서비스 토큰 원문은 발급·로테이션 응답에만 있고
  재조회 경로가 없습니다. 로그·토스트·URL에 싣지 않습니다.

화면의 역할 게이팅은 노이즈 제거이지 통제가 아닙니다. 실제 통제는 backend의 403입니다.

## 디렉터리

```text
src/
├── app/
│   ├── (console)/          인증된 콘솔 레이아웃과 화면
│   ├── login/  403/        공개 경로
│   └── api/                세션 쿠키 Route Handler, 헬스체크
├── components/
│   ├── ui/                 도메인을 모르는 프리미티브
│   └── <domain>/           teams, users, keys, models, settings
├── lib/
│   ├── api/                Admin API 클라이언트와 도메인 조회 (server-only)
│   ├── actions/            Server Action
│   ├── auth/               세션, 페이지 권한표
│   └── format/             날짜·금액·라벨 변환
└── types/api.ts            OpenAPI 계약 타입
```

## 문서

| 문서 | 내용 |
|---|---|
| [docs/00-admin-console-architecture.md](docs/00-admin-console-architecture.md) | 경계, 레이어, 세션·인가, 데이터 페칭·에러·표시 규약 |
| [docs/01-screen-inventory.md](docs/01-screen-inventory.md) | 화면 목록, 역할별 권한, 화면 ↔ API 매핑 |
| [docs/02-implementation-roadmap.md](docs/02-implementation-roadmap.md) | 마일스톤, 테스트 전략, 미결정 사항 |
