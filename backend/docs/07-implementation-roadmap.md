# 07. Implementation Roadmap

| 항목 | 값 |
|---|---|
| 대상 | `backend/` 구현 순서, 테스트 전략, 미결정 사항 |
| 상위 기준 | [docs/implementation-plan.md](../../docs/implementation-plan.md) Phase 1·4 |

## Position in the Overall Plan

저장소 전체 계획의 **Phase 1(control plane 기반)** 과 **Phase 4(집행·관측)** 중 backend 몫이
이 문서의 범위입니다. Phase 1의 스키마와 API 계약이 고정되어야 gateway(Phase 2)와
frontend(Phase 3)가 병렬로 진행할 수 있습니다.

즉 **가장 먼저 끝내야 하는 것은 기능이 아니라 계약**입니다.

## Milestones

### M0 — 계약 고정 (선행, 코드 없음)

gateway 브랜치와 합의해야 하는 항목입니다. 이게 끝나야 M2 이후가 흔들리지 않습니다.

| 항목 | 문서 |
|---|---|
| VK 포맷과 `key_hash` 산출식 | [03](03-virtual-key-management.md) |
| VK 상태 전이와 인증 통과 조건 | [03](03-virtual-key-management.md) |
| Redis 키 이름·TTL·소유권(정책 캐시 / 집행 카운터) | [00](00-admin-api-architecture.md), 05, 06 |
| `usage.usage_events` 컬럼 | [01](01-data-model.md) |
| 예산 기간 경계(UTC 월)와 차단 판정 순서 | [05](05-budget-management.md) |
| rate limit 해석 우선순위 | [06](06-rate-limit-management.md) |
| 허용 모델 해석 규칙 | [04](04-model-catalog.md) |

산출물: gateway 브랜치의 Redis 키 규약 문서 + 이 디렉터리 문서들의 **[공유 계약]** 표시 확정.

### M1 — 프로젝트 골격

- FastAPI 앱 골격, 설정(pydantic-settings), 구조적 로깅, 예외 핸들러, `/healthz`·`/readyz`
- async SQLAlchemy 엔진·세션, Redis 클라이언트, lifespan 배선
- 마이그레이션 컴포넌트 골격 (`backend/db/`: `alembic.ini`, `env.py`, `init/`, `run_migration.sh`, Dockerfile)
- Dockerfile, `pyproject.toml`(uv), lint(ruff)·타입 검사 설정
- backend 실행 방법을 `backend/README.md`에 정리
  (루트 `docker-compose.yml`은 공용 파일이므로 `main`에서 변경합니다 — AGENTS.md 브랜치 규율)

완료 기준: 빈 앱이 뜨고 `/readyz`가 DB·Redis 연결을 확인한다.

### M2 — 스키마와 감사·캐시 기반

- `init/*.sql`: 스키마·확장·DB 역할·GRANT (`backend_app` / `gateway_app`)
- `versions/0001_baseline`: 01 문서의 전 테이블·enum·인덱스·제약
- `AuditLogger`(동기 INSERT), `CacheInvalidationManager`(DEL only + 실패 기록)
- 부트스트랩 관리자 시드

완료 기준: 마이그레이션이 빈 DB에 적용되고, `gateway_app` 역할로 `audit` 스키마 접근이 거부된다.

### M3 — 인증·인가와 팀/사용자 (02)

- OIDC 검증기(JWKS 캐시) + Admin JWT 검증기(`auth.admin_jwt_configs`) + dev 토큰 경로
- 서비스 토큰(`svc-`) 발급·검증·로테이션·폐기
- `get_current_admin`, 역할·소유권 인가 의존성
- 팀/사용자 CRUD, 팀 이동과 파급, 조직 트리
- 감사 기록 + 캐시 무효화 배선

완료 기준: 00 문서의 인가 표대로 403/404가 갈리고, 팀 이동이 VK 캐시 키를 정확히 지운다.

### M4 — Virtual Key (03)

- 발급(원문 1회 반환), 목록·단건, 수정
- 로테이션(유예 + 체인), 폐기(사유 필수), 팀 일괄 폐기
- VK 허용 모델 축소
- 만료·유예 종료 job, 캐시 무효화 재시도 job
- VK 감사 조회 API

완료 기준: 폐기 즉시 `vk:auth:{hash}`가 사라지고, 로테이션 체인이 감사 API에서 이어진다.

### M5 — 모델 카탈로그 (04)

- alias CRUD, 상태 전환
- 단가 시계열 등록·조회, 구간 겹침 차단
- 팀/사용자 허용 모델 CRUD, `effective-models` 해석 API
- 단가 누락 감지 job

완료 기준: 허용 모델 해석이 04 문서의 세 층 규칙과 정확히 일치한다(테이블 주도 테스트).

여기까지가 **Phase 1의 종료 지점**입니다. 이 시점의 OpenAPI 문서가 frontend 착수 계약입니다.

### M6 — 예산 (05)

- 팀/사용자 예산 CRUD, 배분(합계 검증), 소진 조회
- `alert_level` 계산, 예산 미설정 목록
- 소진값 재시드(ADMIN 전용)
- Redis/DB 정합성 검증 job

### M7 — 사용량 집계와 조회

- `usage.usage_events` → 일·월 집계 job
- 팀/사용자/VK/모델 축 조회 API
- 대시보드·리더보드용 조회 API
  ([leaderboard-and-dashboard.md](../../docs/leaderboard-and-dashboard.md)의 지표 정의를 따름)

M7은 gateway가 이벤트를 쓰기 시작해야 검증됩니다. 그 전에는 시드 데이터로 개발합니다.

### M8 — Rate limit (06)

- scope별 설정 CRUD, 계층 제약 검증
- `effective` 해석 API, 트리 조회
- 실시간 사용률 조회(gateway 카운터 규약 확정 후)

M6~M8은 저장소 전체 계획의 Phase 4에 해당하며, gateway·frontend와 병행합니다.

## Dependency Order

```text
M0 (계약)
 └─ M1 (골격)
     └─ M2 (스키마·감사·캐시)
         ├─ M3 (인증·팀/사용자)
         │    └─ M4 (VK) ──┐
         └─ M5 (카탈로그) ──┴─ Phase 1 종료 = frontend/gateway 착수 계약 확정
                             ├─ M6 (예산)
                             ├─ M7 (집계·조회)
                             └─ M8 (rate limit)
```

M4는 M5의 허용 모델 검증을 참조하지만, VK 허용 모델 축소 기능만 M5 이후로 미루면
두 마일스톤을 병행할 수 있습니다.

## Testing Strategy

| 층 | 대상 | 도구 |
|---|---|---|
| 단위 | 해석 규칙(허용 모델, rate limit 우선순위, 예산 판정), 상태 전이, 금액 계산 | pytest |
| 통합 | 라우터 → 서비스 → 실제 PostgreSQL/Redis | pytest + testcontainers |
| 계약 | OpenAPI 스냅샷 비교. 응답 스키마 변경이 리뷰에 드러나게 | pytest |
| 회귀 | 실제로 발견한 버그마다 재현 테스트 1건 | pytest |

반드시 테스트로 고정할 규칙(문서만으로는 구현이 갈리는 지점):

- 허용 모델 3층 해석에서 **"행 0개"의 의미가 층마다 다른 것** (04)
- rate limit **한도 종류별 폴백** 과 GLOBAL 별도 축 (06)
- 예산 **UTC 월 경계** — 특히 KST 기준 월초/월말 (05)
- 팀 이동 시 **캐시 무효화 대상 VK 집합** (02·03)
- 트랜잭션 커밋 **이후** 캐시 삭제 순서 (00)
- 마지막 ADMIN 보호, 배분 합계 초과 거절 (02·05)
- 폐기·만료 키의 인증 컨텍스트 캐시가 남지 않는 것 (03)

통합 테스트는 SQLite로 대체하지 않습니다. partial unique index, `EXCLUDE` 제약, enum, `citext`,
배열 컬럼이 전부 PostgreSQL 고유 기능이라 대체 DB에서는 검증 가치가 없습니다.

## Definition of Done (마일스톤 공통)

- 마이그레이션이 빈 DB에 적용되고, 재적용이 멱등하다.
- 새 상태 변경 API마다 감사 로그 항목이 정의되어 있다.
- 캐시를 건드리는 변경마다 무효화 대상 키가 문서와 코드에서 일치한다.
- OpenAPI에 요청/응답 예시가 있다.
- 위 "반드시 고정할 규칙" 중 해당 항목의 테스트가 있다.

## Open Decisions

확정되면 `main`의 `docs/`에 ADR로 남깁니다. 여기서는 **ADR 후보**로만 표시합니다.

| # | 항목 | 영향 | 판단 시점 |
|---|---|---|---|
| 1 | 사내 IdP 확정과 그룹 → 팀 매핑 규칙, JIT 프로비저닝 활성화 시점 | 00, 02 | IdP 선정 후. 인증 *방식*은 OIDC로 확정됨 |
| 2 | 사용량 기록 경로: gateway 인라인 vs 별도 worker | 01, 05, M7 | gateway의 이벤트 형식 확정 후 |
| 3 | `usage.usage_events` 파티셔닝 도입 시점과 보존 기간 | 01, M7 | 실사용 볼륨이 보인 뒤 |
| 4 | 부서(department) 계층 도입 여부 | 01, 02, 05 | 예산 롤업 요구가 생기면 |
| 5 | `TEAM` 소유 VK 사용량의 사용자 축 표현 | 03, 05, M7 | M7 대시보드 설계 시 |
| 6 | 과거 단가 소급 변경 시 재집계 정책 | 04, M7 | 단가 조정이 실제로 발생할 때 |
| 7 | 429 거절 이력의 영속화 여부 | 06 | gateway 메트릭 설계와 함께 |
| 8 | Bedrock 공시 단가 자동 동기화 도입 여부 | 04 | 수동 등록이 부담이 된 뒤 |
| 9 | 임계 알림 채널과 발송 주체 | 05 | Phase 4 |

## Out of Scope

- **admin-chat-agent** — 참조 구현에 있는 BI 챗 에이전트는 이 프로젝트에서 구현하지 않습니다.
  관련 스키마(`chat_agent`), 라우터, AgentCore 연동, SQL 실행 엔드포인트를 전부 가져오지 않습니다.
- 모델 비교 실험 환경(playground) — 운영 경로 안정화 이후
  ([model-evaluation-playground.md](../../docs/model-evaluation-playground.md))
- 생산성/ROI 지표(코드 수락률, git 이벤트 연동) — 참조 구현의 제품 특화 기능
- 비 Bedrock provider 실구현 — 추상화만 유지
- 자동 모델 다운그레이드, 완전한 chargeback 워크플로
