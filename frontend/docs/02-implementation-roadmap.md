# 02. Implementation Roadmap

| 항목 | 값 |
|---|---|
| 대상 | `frontend/` 구현 순서, 테스트 전략, 미결정 사항 |
| 상위 기준 | [docs/implementation-plan.md](../../docs/implementation-plan.md) Phase 3·4 |

## Position in the Overall Plan

저장소 전체 계획의 **Phase 3(admin 콘솔)** 과 Phase 4의 관측 화면이 이 문서의 범위입니다.
backend M6~M8이 열리면서 관측 화면(F6)까지 착수 조건이 충족되었습니다.

착수 전제는 하나입니다. **backend의 OpenAPI가 계약 원천이고, 프론트는 그것을 따라갑니다.**
없는 API를 가정한 화면을 먼저 만들지 않습니다.

## 진행 상태

| 마일스톤 | 상태 |
|---|---|
| F0 계약 확인 | 완료 |
| F1 앱 골격 | 완료 |
| F2 팀·사용자·조직 | 완료 |
| F3 Virtual Key | 완료 |
| F4 모델 카탈로그·허용 모델 | 완료 |
| F5 설정·내 정보·대시보드 | 완료 |
| F6 관측 화면 | 완료 (backend M6~M8 대응) |

**검증 범위**: 타입 검사(`tsc --noEmit`), lint, 프로덕션 빌드, 단위 테스트 49건이 통과합니다.
로그인 → 세션 쿠키 → 리다이렉트 경로와 Admin API 다운 시 에러 경계 동작은 실행 중인 서버에
직접 요청을 보내 확인했습니다.

**브라우저 검증**: 시드 데이터가 들어간 backend를 띄우고 ADMIN 조회 흐름을 실제 브라우저로
확인했습니다 — 기록은 [03-local-browser-verification.md](03-local-browser-verification.md).
drill-down 필터 전파, 예산 경보 단계, 소진값 출처 표시, rate limit 실효값 상속이 backend 응답과
일치합니다. 검증 중 개발 모드 CSP가 화면을 막던 문제를 고쳤습니다.

**미검증 항목**: 실제 사용자 ID 기반의 TEAM_LEADER/MEMBER 인가, 변경 조작(발급·수정·폐기·배분
저장·재시드), gateway 집행 연동, 모바일 폭입니다. 변경 조작은 시드를 되돌릴 방법이 있어야
반복 검증이 되므로, 그 준비와 함께 진행합니다.

**검증에서 나온 미해결 항목** (03 문서 "남은 발견 사항"):

| # | 항목 | 소유 |
|---|---|---|
| 1 | 리더보드 drill-down 링크가 이름 셀에만 걸려 있어 안내 문구("행을 누르면")와 다름 | frontend |
| 2 | 금액 포매터가 `0E-8` 같은 지수 표기를 그대로 노출 | frontend (직렬화 규약은 backend와 함께) |
| 3 | 예산 소진값 `source:db`·`used_usd:0`이 "집계 0"과 "사본 없음"을 구분하지 못함 | backend |

3번은 응답에 구분이 없으면 화면에서 추측할 수 없습니다. backend에 구분 가능한 응답을
요청하는 것이 맞고, 그때까지 화면은 받은 값을 그대로 보여줍니다.

## Milestones

### F0 — 계약 확인 (코드 없음)

backend의 OpenAPI에서 경로·스키마·enum을 뽑아 `src/types/`에 옮깁니다.
직접 손으로 옮기되, **backend 스키마 이름을 그대로 씁니다.** 이름을 바꾸면 나중에 응답과
화면 타입을 대조하기 어려워집니다.

확인 대상: 29개 경로, 커서 페이지네이션 봉투, 에러 봉투, 금액 문자열 직렬화, enum 6종
(`UserRole`, `VKStatus`, `VKOwnerType`, `RevokeReason`, `ModelStatus`, `ApiDialect`).

F6 착수 시 같은 방식으로 M6~M8 계약을 옮겼습니다 — enum 7종(`BudgetScope`, `BudgetPeriod`,
`BudgetPolicy`, `AlertLevel`, `RateLimitScope`, `UsageAxis`, `UsageMetric`,
`TrendGranularity`)과 예산·rate limit·사용량 응답 타입. **`alert_level`과 `failure_rate_pct`는
backend가 계산해 내려주는 값이고 프론트가 다시 계산하지 않습니다.** 같은 규칙을 두 곳에서
구현하면 화면과 집행이 갈라집니다.

### F1 — 앱 골격

- Next.js 15 App Router 스캐폴딩, TypeScript strict, Tailwind 토큰, lint/format
- `AdminApiClient` — 쿠키 → Bearer 전달, 에러 봉투 → `AdminApiError` 변환, GET 재시도
- 세션 Route Handler (dev 로그인 / 로그아웃), `middleware.ts` 인증 게이트
- 콘솔 레이아웃 (사이드바·헤더·테마), `GET /me` 기반 역할 인가와 `/403`
- 공통 UI 프리미티브: Button, Table, Badge, Dialog, Select, Toast, Pagination, EmptyState
- `Dockerfile`, `.env.example`, `frontend/README.md`

완료 기준: 로그인 → 콘솔 진입 → 역할에 맞는 내비게이션이 뜬다.

### F2 — 팀·사용자·조직 (backend M3)

- 팀 목록·생성·수정, 팀 상세(멤버·팀장 지정)
- 사용자 목록(필터·커서)·생성·수정·비활성화·팀 이동
- 조직 트리
- 파급 결과(`revoked_virtual_keys`, `cache_invalidated`) 표시

완료 기준: 팀 이동이 영향받은 VK 수와 캐시 무효화 성공 여부를 화면에 그대로 드러낸다.

### F3 — Virtual Key (backend M4)

- 목록(소유자·상태·만료·미사용 필터), 발급, 수정, 로테이션, 폐기(사유 필수)
- 원문 1회 노출 다이얼로그
- 상세: 감사 이력과 로테이션 체인

완료 기준: 발급·로테이션 원문이 다이얼로그를 닫는 순간 사라지고 어디에도 재조회 경로가 없다.

### F4 — 모델 카탈로그·허용 모델 (backend M5)

- 카탈로그 목록·등록·수정·상태 전환, 단가 누락 목록
- 단가 시계열 조회와 등록(구간 겹침은 backend 409를 그대로 표시)
- 팀/사용자 허용 모델 설정, 실효 모델 해석 결과 표시

완료 기준: 설정값과 실효값이 나란히 보이고 `resolved_from`으로 이긴 층이 드러난다.

### F5 — 설정·내 정보·대시보드

- 서비스 토큰 발급·로테이션·폐기
- 캐시 무효화 재시도
- `/my` — 내 계정, 실효 허용 모델, 내 키
- 대시보드 운영 점검판 (01 문서의 카드 목록)

완료 기준: 단가 누락과 캐시 무효화 실패가 첫 화면에서 보인다.

### F6 — 관측 화면 (backend M6~M8)

- `/usage` — 합계·추이·리더보드·정책 거절. 네 조회가 같은 필터를 쓰고, 리더보드 행이
  자기 축의 필터를 URL에 붙여 drill-down합니다.
- `/budgets`, `/budgets/team/[teamId]` — 소진 요약, 미설정 목록, 팀 예산 설정·해제,
  멤버 배분(전체 교체), 소진값 재시드(ADMIN)
- `/rate-limits` — 전역 축과 주체 축을 따로, 팀→멤버 트리와 종류별 실효값, 실시간 사용률
- `/keys/[keyId]`에 VK 한도와 실효 한도, `/my`에 내 예산, `/`에 최근 사용량과 예산 경보

완료 기준: 예산 미설정과 경보가 첫 화면에서 보이고, 한도가 **왜 그 값인지**(`resolved_from`)를
화면이 설명한다.

**차트 라이브러리는 도입하지 않았습니다**(미결정 #2 결론). 필요한 것은 "어느 날 튀었는가"
하나이고 CSS 막대로 충분합니다. 라이브러리는 번들과 테마·SSR 대응 비용을 함께 들여옵니다.
축·범례·줌이 필요한 지표가 생기면 그때 도입합니다 — 그 판단 근거를 남겨 두는 것이 이 항목의
목적입니다.

## Dependency Order

```text
F0 (계약)
 └─ F1 (골격: 클라이언트·세션·레이아웃·프리미티브)
     ├─ F2 (팀·사용자) ──┐
     ├─ F3 (VK)        ──┤
     └─ F4 (모델·허용)  ──┴─ F5 (설정·내 정보·대시보드)
                                    └─ F6 (관측)  ← backend M6~M8
```

F2·F3·F4는 서로를 기다리지 않습니다. 다만 F3의 소유자 선택과 F4의 허용 모델 선택이
F2의 팀/사용자 조회를 재사용하므로, F2를 먼저 끝내면 중복 구현이 줄어듭니다.

## Testing Strategy

| 층 | 대상 | 도구 |
|---|---|---|
| 타입 | 계약 타입과 화면의 일치 | `tsc --noEmit` |
| 단위 | 표시 변환(금액·날짜·상태), 에러 봉투 파싱, 페이지 권한표 | vitest |
| 빌드 | 프로덕션 빌드 성공 | `next build` |

반드시 테스트로 고정할 규칙(문서만으로는 구현이 갈리는 지점):

- **금액 문자열이 숫자로 변환되지 않는 것** — 표시 포맷을 거쳐도, **합산을 거쳐도** 정밀도가
  유지되어야 합니다. 배분 합계는 1/10000 단위 정수로 더합니다(`sumDecimals`).
- 에러 봉투(`{error:{code,message,...}}`) 파싱과, 봉투가 아닌 응답(502 HTML 등)의 폴백.
- 422 검증 오류가 필드 단위로 풀리는 것.
- 페이지 권한표의 기본 거부 — 표에 없는 경로는 허용되지 않습니다.
- 커서 페이지네이션에서 `has_more=false`일 때 다음 버튼이 죽는 것.
- 조회 기간이 **양끝 포함**으로 세어지고, 상한(366일)·역순·형식 오류가 기본 기간으로 되돌아가는 것.
- 추이의 빈 버킷이 **0이 아니라 없음**으로 남는 것 — 집계가 안 돈 날과 호출이 없던 날의 구분.
- 예산 미설정(무제한)과 한도 0(쓸 수 없음)이 다른 문구로 표시되는 것.

E2E(Playwright)는 backend 통합 환경이 서고 난 뒤 도입합니다. 지금 붙이면 목 서버를 상대로
목을 검증하게 됩니다.

## Definition of Done (마일스톤 공통)

- `npm run typecheck`, `npm run lint`, `npm run build`가 통과한다.
- 새 화면마다 로딩·빈 상태·오류 상태가 각각 정의되어 있다.
- 변경 조작마다 성공/실패 피드백이 있고, 실패 시 `request_id`가 보인다.
- 비밀값(VK 원문, 서비스 토큰 원문)이 URL·로그·재조회 경로에 남지 않는다.
- 역할별로 보이는 내비게이션과 버튼이 01 문서의 권한표와 일치한다.

## Open Decisions

확정되면 `main`의 `docs/`에 ADR로 남깁니다. 여기서는 **ADR 후보**로만 표시합니다.

| # | 항목 | 영향 | 판단 시점 |
|---|---|---|---|
| 1 | OIDC IdP 확정과 로그인 진입 방식(콘솔이 authorization code flow를 직접 수행할지, 프록시/ALB가 앞에서 끝낼지) | 00, F1 | backend 07 미결정 #1과 함께 |
| ~~2~~ | ~~차트 라이브러리 선정~~ | ~~F6~~ | **결정됨 — 도입하지 않음**. 위 F6 항목 참조 |
| 3 | 목록 화면의 "이전 페이지" 제공 범위 — 커서 스택을 URL에 쌓는 방식의 한계 | 00 | 실사용 데이터 규모가 보인 뒤 |
| 4 | 감사 로그 전체 조회 화면 도입 | 01 | backend에 목록 API가 생기면 |
| 5 | 프론트 관측(OpenTelemetry) 도입 여부 | 00 | 배포 표준이 정해진 뒤 |

## Out of Scope

- **챗 어시스턴트** — 참조 구현의 BI 챗 화면은 구현하지 않습니다(backend 07 문서와 동일).
- **생산성/ROI 지표 화면** — 우리 usage 이벤트에 해당 축이 없습니다.
- **모델 비교 playground** — 운영 경로 안정화 이후(`docs/model-evaluation-playground.md`).
- **CLI 배포 화면** — 참조 구현의 제품 특화 기능.

## Related Documents

- [00-admin-console-architecture.md](00-admin-console-architecture.md)
- [01-screen-inventory.md](01-screen-inventory.md)
