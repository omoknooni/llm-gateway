# AGENTS.md

## Repository Context

사내 공통 LLM Gateway와 중앙 비용 관제 플랫폼을 구현하는 저장소입니다.
Gateway(data plane)와 Admin API(control plane)를 **서드파티 proxy 제품에 의존하지 않고 직접 구현**합니다.
참조 구현은 `awsome-ai-gateway`(AWS EKS 기반)이며, 코드를 그대로 가져오지 않고 컴포넌트 분리 방식만 참고합니다.

이전 LiteLLM wrapper 기준선은 폐기되었습니다. 근거는 [ADR-0001](docs/adr-0001-self-hosted-data-plane.md).

## Repository Layout

| 디렉터리 | 역할 | 작업 브랜치 |
|---|---|---|
| `backend/` | admin 서비스의 API. 정책의 source of truth | `feat/admin-backend` |
| `frontend/` | admin API를 소비하는 Next.js SSR 콘솔 앱 | `feat/admin-frontend` |
| `gateway/` | client API 진입점. VK 인증, Bedrock 호출 프록시 | `feat/gateway` |
| `infra/chart/` | 위 3개 앱의 Kubernetes 배포용 Helm chart | `main` |
| `infra/terraform/` | llm-gateway용 AWS 클라우드 리소스 정의 | `main` |
| `docs/` | 설계 문서 및 ADR | `main` |

## Default Technical Direction

- Gateway (data plane): Python + FastAPI, 자체 구현. OpenAI 호환(`/v1/chat/completions`)과
  Anthropic Messages(`/v1/messages`) 두 방언을 모두 노출
- Admin API (control plane): Python + FastAPI, async SQLAlchemy, Alembic
- Admin Console: Next.js (App Router) + TypeScript, SSR 유지
- Model backend: AWS Bedrock
- Data layer: PostgreSQL (Amazon RDS) + Redis (Amazon ElastiCache)
- Compute: Amazon EKS (Helm chart로 배포, 권한은 IRSA)
- Identity source: 사내 SSO / IdP
- Cost estimation baseline: Bedrock on-demand pricing

DB와 캐시는 클러스터 내부에 상주시키지 않고 외부 매니지드 엔드포인트로 주입받습니다.
client는 Claude 외 모델도 사용하므로, 모델 선택이 요청 방언에 묶이지 않아야 합니다.

## Working Principles

- 실제 Bedrock 자격 증명은 외부에 노출하지 않고 Virtual Key만 발급합니다.
- **plane 분리**: data plane과 control plane은 코드를 공유하지 않고 DB 스키마와 Redis 키 규약으로만 만납니다.
  gateway는 backend의 HTTP API를 호출하지 않습니다.
- **캐시 소유권**: control plane은 정책 변경 시 캐시를 *무효화만* 하고, 값을 채우는 주체는 gateway입니다.
- **마이그레이션 소유권**: Alembic 마이그레이션의 단일 소유자는 `backend/`입니다. gateway는 같은 스키마를 읽되 정의하지 않습니다.
- 공통 규약: 모든 엔터티 PK는 UUID, 금액은 `Decimal`(부동소수점 금지), 시간은 timezone-aware UTC.
- 팀/사용자/Virtual Key/모델 축으로 사용량과 추정 비용이 집계되어야 합니다.
- 장기 AWS 자격 증명을 이미지나 코드에 포함하지 않습니다. Bedrock 권한은 IRSA로 부여하고,
  코드는 자격 증명 획득을 기본 credential chain에 위임합니다.
- **방언 중립**: 인증·정책 집행·사용량 이벤트 발행은 요청 방언과 무관하게 동일 경로를 지납니다.
  방언은 파싱과 직렬화 계층에만 존재합니다.
- 세부 기능 설계는 이 파일에 길게 적지 않고 `docs/` 하위 문서로 확장합니다.

## Branch Discipline

- 각 브랜치는 자기 디렉터리(`backend/`, `frontend/`, `gateway/`)와 대응 문서만 수정합니다.
- 공용 파일(`README.md`, `AGENTS.md`, `docs/`, `docker-compose.yml`, `infra/`)은 `main`에서 변경한 뒤 각 worktree로 전파합니다.
- 통합은 각 브랜치 → `main` 방향이며, 브랜치 간 직접 병합은 하지 않습니다.

## Read These Docs First

- [docs/implementation-plan.md](docs/implementation-plan.md) — 구현 순서, 컴포넌트 경계, 공유 계약
- [docs/virtual-key-management.md](docs/virtual-key-management.md)
- [docs/usage-and-cost-observability.md](docs/usage-and-cost-observability.md)
- [docs/leaderboard-and-dashboard.md](docs/leaderboard-and-dashboard.md)
- [docs/model-evaluation-playground.md](docs/model-evaluation-playground.md)

## Accepted Decisions

- [ADR-0001](docs/adr-0001-self-hosted-data-plane.md): LiteLLM 의존 제거, gateway 자체 구현
- [ADR-0002](docs/adr-0002-deployment-target-eks.md): 배포 대상은 Amazon EKS (IRSA + ALB Ingress)
- [ADR-0003](docs/adr-0003-client-api-dialects.md): OpenAI 호환 + Anthropic Messages 동시 지원

새 아키텍처 결정은 [docs/adr-template.md](docs/adr-template.md)를 사용해 ADR로 남깁니다.

## Expected Output Style

- README는 프로젝트 개요와 전체 구조를 설명합니다.
- `docs/` 문서는 기능별 instruction과 구현 기준을 설명합니다.
- 구현 시에는 문서에 나온 엔터티 이름과 책임 경계를 우선 유지합니다.
