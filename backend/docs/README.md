# backend/docs — Admin API 구현 계획

`backend/`(control plane, Admin API)의 구현 계획 문서 모음입니다.
상위 기준선은 저장소 루트의 [AGENTS.md](../../AGENTS.md)와 [docs/implementation-plan.md](../../docs/implementation-plan.md)이며,
이 디렉터리는 그 기준선을 backend 구현 수준으로 내린 결과입니다.

참조 구현은 `awsome-ai-gateway`의 `admin-api`입니다. 코드를 그대로 가져오지 않고
컴포넌트 분리 방식과 도메인 경계만 참고하며, 참조 구현과 다르게 가는 지점은 각 문서의
**참조 구현과의 차이** 절에 근거와 함께 남깁니다.

## 읽는 순서

| 문서 | 내용 |
|---|---|
| [00-admin-api-architecture.md](00-admin-api-architecture.md) | 서비스 경계, 레이어, 관리자 인증/인가, 에러·감사·캐시 무효화 규약 |
| [01-data-model.md](01-data-model.md) | PostgreSQL 스키마 전체, Alembic 소유권, 공통 타입 규약 |
| [02-team-and-user-management.md](02-team-and-user-management.md) | 팀/사용자 CRUD, 역할, 팀 이동 시 파급 |
| [03-virtual-key-management.md](03-virtual-key-management.md) | VK 발급·로테이션·폐기·감사, 키 저장 방식 |
| [04-model-catalog.md](04-model-catalog.md) | 모델 alias CRUD, 단가 시계열, 허용 모델 정책 |
| [05-budget-management.md](05-budget-management.md) | 예산 설정/배분 CRUD, 소진 조회, 집행 계약 |
| [06-rate-limit-management.md](06-rate-limit-management.md) | rate limit 설정 CRUD, 우선순위 해석, 집행 계약 |
| [07-implementation-roadmap.md](07-implementation-roadmap.md) | 마일스톤, 순서, 테스트 전략, 미결정 사항 |
| [08-shared-contracts.md](08-shared-contracts.md) | gateway와 공유하는 계약 모음 (키 규약, 해석 규칙, DB 경계) |
| [09-gateway-contract-response.md](09-gateway-contract-response.md) | gateway 회신 결과, 스키마 변경 요청 S1~S4 처리, 확인 대기 항목 |
| [10-usage-aggregation.md](10-usage-aggregation.md) | 사용량 집계 job, 지표 정의, 대시보드·리더보드 조회 API |

## 문서 규칙

- 이 디렉터리의 문서는 `feat/admin-backend` 브랜치에서만 수정합니다.
- 아키텍처 결정(ADR)은 이 디렉터리가 아니라 `main`의 `docs/`에 남깁니다.
  여기서는 "ADR 후보"로 표시만 하고, 확정되면 `main`에서 ADR 번호를 받습니다.
- gateway와 공유하는 계약(DB 스키마, Redis 키, 상태 전이 규칙)은 별도로 표시합니다.
  이 표시가 붙은 항목은 backend 단독으로 바꿀 수 없습니다.
