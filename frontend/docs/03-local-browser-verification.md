# 로컬 브라우저 검증 — 2026-09-13 (KST)

## 환경과 범위

- FE `http://localhost:3000`, BE `http://localhost:8000`, 개발 로그인 ADMIN.
- Chromium 153 / Playwright, 1440×1000 화면. API 응답 모킹 없이 실행 중인 시드 데이터 사용.
- 기본 사용량 기간: 2026-08-14 ~ 2026-09-12 (UTC), 예산: 2026-09.
- 로그인, 목록·상세 조회, 필터·링크 클릭을 검증했다. 발급·수정·폐기·재시드는 실행하지 않았다.
- 브라우저 도구와 캡처는 `/tmp/admin-fe-browser-check/`에 있으며 저장소 의존성에 추가하지 않았다.

## 검증 중 수정한 차단 오류

`next.config.ts`의 CSP가 개발용 Webpack의 스크립트 평가를 차단했다.
개발 로그인은 일반 HTML 폼이라 동작했지만 이후 여러 화면은 로딩 스켈레톤에 머물렀고,
브라우저에 `unsafe-eval` CSP 오류가 발생했다.

`NODE_ENV=development`에서만 `script-src`에 `unsafe-eval`을 추가했다.
수정 후 주요 화면을 재탐색했으며 수집한 브라우저 오류는 0건이었다.
설정을 별도로 평가해 production에는 `unsafe-eval`이 포함되지 않는 것도 확인했다.

## 주요 확인 결과

| 대상 | 결과 |
|---|---|
| `/usage` 팀 이름 클릭 | 전체 824건 / $48.09 → search-platform 516건 / $29.93. 합계·추이·리더보드 모두 변경 |
| 사용자 축 클릭 | `(팀 공용 키)` 169건 / $10.58로 축소. 공용 키의 사용자 UUID sentinel 필터도 동작 |
| 모델 축 클릭 | claude-opus-4 274건 / $38.29로 축소 |
| Virtual Key 축 클릭 | 검색팀 공용 배치 169건 / $10.58로 축소 |
| 필터 유지 | 팀 drill-down 후 정렬 지표를 호출 수로 바꾸고 적용해도 team_id 유지 |
| 추이 정합성 | 네 축 각각 BE 추이 버킷 호출 수 합계와 overview 호출 수 일치 |
| `/budgets` 출처 | 현재 월 `실시간(집행 카운터)` / 이전 월 `집계값(DB)` 표시, BE source와 일치 |
| 예산 경보 | 팀: WARNING 81.24%, CRITICAL 97.00%. 사용자: NORMAL 32.38%, CRITICAL 99.08%, EXCEEDED 102.34% |
| 예산 초과 | 박랭킹 남은 금액 -8.20달러, 초과 배지 확인 |
| 미설정 카드 | data-lab·platform 2팀, 사용자 4명 표시. data-lab 상세에서 무제한·배분 불가 안내 확인 |
| `/rate-limits` | BE `available:false`, `entries:[]`와 화면 `관측 불가` 일치. 예상된 상태 |
| 한도 실효값 | search-platform 및 claude-sonnet-4 선택 시 이색인 RPM 100은 USER, TPM 400000과 동시 실행 40은 TEAM에서 상속 |

## 전반적인 화면 확인

- 대시보드: 팀 4, 활성 사용자 7, 활성 VK 5, 만료 임박 VK 1, 단가 누락 0.
- 팀·사용자·조직 트리: 팀 4 / 사용자 8 / 비활성 사용자 1과 platform의 빈 멤버 상태 표시.
- VK: ACTIVE 5 / ROTATED 1 / REVOKED 1 / EXPIRED 1, TEAM 공용 키 표시.
  신 키 상세의 로테이션 체인과 감사 이벤트 표시 확인.
- 모델: 4개와 INACTIVE 1개, 단가 표시. claude-opus-4 상세의 BEDROCK_MANTLE 확인.
- 서비스 토큰: 기본 활성 1개, 폐기 포함 필터 선택 시 폐기 토큰까지 2개 표시.
- 캐시: 재시도 실행 전 안내 정상 표시.
- ADMIN의 `/my` 접근은 `/403`으로 이동한다. 현재 페이지 권한표의 의도된 동작이다.

## 남은 발견 사항

### 리더보드의 클릭 영역과 안내가 다름

`/usage`는 “행을 누르면”이라고 설명하지만 실제 링크는 첫 셀의 이름에만 있다.
비용 셀을 클릭하면 이동하지 않고, 이름을 클릭하면 정상적으로 전체 필터가 적용된다.
행 전체 클릭 요구사항 기준으로는 부분 통과다. 클릭 영역 확장 또는 안내 문구 정리가 필요하다.

### DB 출처의 예산 0원은 실제 사용량 0원을 뜻하지 않음

2026-08 예산 summary는 두 팀 모두 `source:db`, `used_usd:0`을 반환한다.
같은 달 usage API에는 search-platform $24.068533, payments $7.839437이 존재한다.
data-lab의 2026-09 상세도 상단 소진 $0.00과 하단 월 집계 $2.96이 함께 표시된다.

BE `UsageReader`는 Redis 다음으로 `BudgetUsage`를 조회하고, 행이 없으면 0과 `source:db`를
반환한다. 이 경로는 사용량 월 집계와 다르다. FE는 응답을 그대로 표시하고 있다.
현재 시드의 예산 소진 사본 정합성 및 “집계값(DB)” 문구의 정확성은 BE와 함께 검토해야 한다.
누락과 실제 0을 구별하려면 API 응답에서도 구분이 필요하다.

### 모델 캐시 단가의 지수 표기

claude-opus-4 단가 이력에서 캐시 쓰기·읽기 0이 `$0E-8`로 표시된다.
현재 금액 포매터는 일반 소수 문자열만 처리하므로 Decimal 지수 표기가 그대로 노출된다.
금액 정밀도를 유지하는 지수 표기 지원 또는 BE 직렬화 규약 정리가 필요하다.

## 검증 한계와 자동 검사

- ADMIN 조회 흐름을 검증했다. 실제 사용자 ID 기반 TEAM_LEADER/MEMBER 인가, CRUD 저장,
  Gateway 집행, 실제 Bedrock 호출, 모바일 화면은 이번 검증 범위에 포함하지 않았다.
- Redis 장애를 유발하지 않았다. DB 출처는 과거 월 조회로 확인했다.
- typecheck / ESLint 통과, Vitest 7개 파일 49개 테스트 통과.
- 임시 증거: `artifacts/usage*.png`, `budgets*.png`, `rate-limits*.png`,
  `interactions.json`, `details.json`, `errors.json`. `/tmp` 정리 시 사라질 수 있다.
