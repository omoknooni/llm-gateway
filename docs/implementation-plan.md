# Implementation Plan

## Objective

LiteLLM 의존을 제거하고 control plane과 data plane을 모두 자체 구현하는 llm-gateway를
어떤 경계로, 어떤 순서로 만들지 정의합니다. 각 구현 브랜치가 공유하는 기준선 문서입니다.

## Repository Layout

```text
llm-gateway/
├── backend/          admin 서비스 API (control plane, FastAPI)
├── frontend/         admin 콘솔 앱 (Next.js SSR)
├── gateway/          client API 진입점 (data plane, FastAPI proxy)
├── infra/
│   ├── chart/        위 3개 앱의 Kubernetes 배포용 Helm chart
│   └── terraform/    llm-gateway용 AWS 클라우드 리소스
├── docs/             설계 문서 및 ADR
└── docker-compose.yml  로컬 개발용 의존 스택 (postgres/redis)
```

## Component Boundaries

```text
Client (SDK / 내부 서비스)
   │  Authorization: Bearer <virtual key>
   ▼
gateway (data plane)
   ├─ VK 인증 → 정책 집행(허용 모델 / rate limit / 예산) → Bedrock 호출
   └─ usage event 발행 ──────────────┐
                                     ▼
Admin (browser) → frontend (SSR) → backend (control plane) → PostgreSQL / Redis
```

- **Data plane** (`gateway/`) — 지연에 민감하고 QPS가 높습니다. 요청 경로에서 PostgreSQL을
  직접 조회하지 않는 것을 목표로 하며, 정책은 Redis 캐시에서 읽고 miss일 때만 DB로 내려갑니다.
- **Control plane** (`backend/`, `frontend/`) — 사람 대상, 저 QPS입니다. 정책의 source of truth이며
  DB에 직접 씁니다.
- gateway는 backend의 HTTP API를 호출하지 않습니다. 두 plane은 **DB 스키마와 Redis 키 규약**으로만
  만납니다.
- frontend는 브라우저에서 backend를 직접 호출하지 않고 SSR 서버 또는 route handler를 경유합니다.
- 사용량 이벤트는 gateway가 쓰고 backend가 읽습니다. 쓰기 주체와 읽기 주체를 섞지 않습니다.

## Shared Contracts

구현 브랜치가 서로를 기다리지 않도록, 아래 계약은 착수 시점에 먼저 고정합니다.

| 계약 | 소유자 | 내용 |
|---|---|---|
| DB 스키마 / Alembic | `backend/` | 단일 마이그레이션 경로. gateway는 읽되 정의하지 않음 |
| Redis 키 규약 | `gateway/` | 정책 캐시, rate limit 카운터, usage 이벤트 스트림의 키 이름과 TTL |
| 캐시 무효화 규칙 | 공통 | control plane은 캐시 키를 **삭제만** 하고, 값을 채우는 주체는 gateway |
| Admin API 스펙 | `backend/` | FastAPI가 생성하는 OpenAPI 문서가 frontend의 계약 원천 |
| 공통 타입 | 공통 | PK는 UUID, 금액은 `Decimal`, 시간은 timezone-aware UTC |

## Build Order

| Phase | 내용 | 브랜치 |
|---|---|---|
| 0 | 기준선 정리 — LiteLLM 구현물 제거, 디렉터리 골격과 기준 문서 (완료) | `main` |
| 1 | control plane 기반 — DB 스키마, Alembic, 관리자 인증, 팀/사용자/모델 카탈로그/VK CRUD | `feat/admin-backend` |
| 2 | data plane — VK 인증, 두 방언 파싱, 모델 alias 라우팅, Bedrock 호출(non-stream → stream), usage 이벤트 발행 | `feat/gateway` |
| 3 | admin 콘솔 — 로그인, 팀/사용자/키 관리, 모델 카탈로그 화면 | `feat/admin-frontend` |
| 4 | 집행과 관측 — rate limit·예산 집행, 사용량 집계, 대시보드/리더보드 | 각 브랜치 |
| 5 | 배포 — Helm chart, Terraform | `main` |

Phase 1의 스키마·API 계약이 고정된 뒤 Phase 2와 3은 병렬로 진행합니다.

## Branch and Worktree Strategy

| 작업 | 브랜치 | worktree 경로 |
|---|---|---|
| admin backend | `feat/admin-backend` | `../llm-gateway-worktrees/admin-be` |
| admin frontend | `feat/admin-frontend` | `../llm-gateway-worktrees/admin-fe` |
| gateway | `feat/gateway` | `../llm-gateway-worktrees/gateway` |

- 각 브랜치는 자기 디렉터리와 대응 문서만 수정합니다.
- 공용 파일(`README.md`, `AGENTS.md`, `docs/`, `docker-compose.yml`, `infra/`)은 `main`에서 변경한 뒤
  각 worktree로 전파합니다. 전파는 `git merge --ff-only main` 또는 `git rebase main`을 사용합니다.
- 통합은 각 브랜치 → `main` 방향이며, 브랜치 간 직접 병합은 하지 않습니다.

## Client Interface

gateway는 **OpenAI 호환과 Anthropic Messages 두 방언을 모두** 노출합니다.
client가 Claude 외 모델도 사용하므로 한쪽 방언에 묶이지 않아야 합니다.
근거는 [ADR-0003](adr-0003-client-api-dialects.md).

- OpenAI 호환: `/v1/chat/completions`, `/v1/models`
- Anthropic Messages: `/v1/messages`
- 두 방언은 동등하며, 한쪽을 다른 쪽으로 변환해 내보내지 않습니다.
- 내부 구조는 `dialect → 정규화된 내부 표현 → provider adapter`입니다. 방언 수와 provider 수가
  곱해지지 않게 유지합니다.
- 인증·정책 집행·사용량 이벤트 발행은 방언과 무관하게 동일 경로를 지납니다.
  방언은 파싱과 직렬화 계층에만 존재합니다.
- 두 방언 모두 스트리밍을 지원하고, 미지원 필드는 조용히 무시하지 않고 명시적으로 거절합니다.

## Deployment Baseline

애플리케이션 배포 대상은 **Amazon EKS**입니다. 근거는 [ADR-0002](adr-0002-deployment-target-eks.md).

- `infra/chart/`의 Helm chart가 3개 앱을 배포합니다. 워크로드별 ServiceAccount에 **IRSA**를 연결해
  AWS 권한을 부여하고, Ingress는 **AWS Load Balancer Controller**를 기본 구현체로 씁니다.
- `infra/terraform/`는 EKS 클러스터, IRSA용 IAM role과 OIDC provider, RDS, ElastiCache, ECR,
  시크릿 저장소를 정의합니다. `infra/chart/`와 서로의 역할을 침범하지 않습니다.
- PostgreSQL은 Amazon RDS, Redis는 Amazon ElastiCache를 사용하며 클러스터 내부에 상주시키지 않습니다.
- 모델 호출은 Amazon Bedrock을 사용하고, 접근 권한은 IRSA로 부여합니다.
  장기 AWS 액세스 키를 이미지나 Secret에 두지 않습니다.
- 애플리케이션 코드에는 CSP별 분기를 두지 않습니다. 자격 증명 획득은 기본 credential chain에
  위임해, 운영(IRSA)과 로컬(개발자 AWS 프로필)이 같은 코드로 동작하게 합니다.
- `gateway`만 공개 진입점으로 노출하고, `backend`와 `frontend`는 내부 경계 뒤에 둡니다.
- 노드 형태(Fargate vs 관리형 노드그룹)는 미확정입니다.

## Open Decisions

착수 전에 확정이 필요하지만 아직 결정되지 않은 항목입니다. 확정 시 ADR로 남깁니다.

- **비용 기록 경로** — usage 이벤트를 gateway가 인라인 기록할지, 별도 worker로 분리할지.
  이벤트 발행 형식이 확정된 뒤 판단합니다.
- **관리자 인증** — 초기 로컬 관리자 계정에서 사내 SSO/IdP로 전환하는 시점과 방식.
- **EKS 노드 형태** — Fargate와 관리형 노드그룹 중 어느 쪽을 기본으로 둘지.
  워크로드 특성이 드러난 뒤 정합니다.

## Out of Scope for Now

- 모델 비교 실험 환경(playground)은 운영 경로가 안정된 뒤 착수합니다.
  [model-evaluation-playground.md](model-evaluation-playground.md)
- multi-provider(비 Bedrock) 확장은 provider 추상화만 유지하고 구현하지 않습니다.
- 완전한 chargeback 워크플로와 자동 예산 제어.

## References

- [ADR-0001: gateway 자체 구현](adr-0001-self-hosted-data-plane.md)
- [ADR-0002: 배포 대상 Amazon EKS](adr-0002-deployment-target-eks.md)
- [ADR-0003: OpenAI 호환 + Anthropic Messages 동시 지원](adr-0003-client-api-dialects.md)
- [virtual-key-management.md](virtual-key-management.md)
- [usage-and-cost-observability.md](usage-and-cost-observability.md)
- [leaderboard-and-dashboard.md](leaderboard-and-dashboard.md)
- 참조 구현: `awsome-ai-gateway` (admin-api / admin-ui / gateway-proxy / cost-recorder-worker)
