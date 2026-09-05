# Internal LLM Gateway

사내 공통 LLM Gateway와 중앙 비용 관제 플랫폼입니다. AWS Bedrock 모델 호출을 표준 인터페이스로
통일하고, 팀/개인 단위 접근 제어와 Virtual Key 발급, 사용량 집계, 비용 추정, 리더보드 시각화를
하나의 구조로 제공합니다.

Gateway(data plane)와 Admin API(control plane)는 서드파티 proxy 제품에 의존하지 않고 직접 구현합니다.
배경과 근거는 [ADR-0001](docs/adr-0001-self-hosted-data-plane.md)에 있습니다.

## Why This Project Exists

여러 팀이 개별적으로 Bedrock을 호출하면 다음 문제가 빠르게 발생합니다.

- 모델 호출 인터페이스가 팀별로 달라 운영 복잡도가 높아집니다.
- 실제 AWS 자격 증명이 분산 노출되어 보안 통제가 어려워집니다.
- 누가 어떤 모델을 얼마나 사용했고 비용이 얼마나 발생했는지 중앙에서 보기 어렵습니다.
- 고정형 구독 모델과 종량제 모델의 비용 효과를 데이터로 비교하기 어렵습니다.

## Goals

- 팀/개인별 사용량을 중앙에서 통제할 수 있는 사내 LLM Gateway 플랫폼 구현
- Bedrock 모델을 동일 인터페이스로 호출할 수 있도록 표준화
- Virtual Key 기반 인증으로 실제 클라우드 자격 증명 비노출
- 키 로테이션, 폐기, 사용 이력 추적 및 팀/개인 단위 접근 제어
- 팀, 사용자, Virtual Key, 모델 기준의 사용량/비용 관제
- 누적 호출량, 토큰 사용량, 추정 비용 기준 리더보드 제공
- 종량제 전환 효과를 검증할 수 있는 비용 분석 기반 마련

## Architecture

플랫폼은 두 개의 plane으로 나뉩니다.

- **Data plane** — `gateway`가 client 요청을 받아 인증·정책 집행·Bedrock 호출을 수행합니다.
  지연에 민감하고 QPS가 높습니다.
- **Control plane** — `frontend` → `backend`로 이어지는 관리 경로입니다. 정책의 source of truth이며
  사람이 사용합니다.

```text
Client App / Internal Service
        │  Authorization: Bearer <virtual key>
        ▼
┌─────────────────────── DATA PLANE ────────────────────────┐
│ gateway (FastAPI)                                          │
│  Auth → AuthZ → Budget → RateLimit →                       │
│  ModelResolve → Bedrock Invoke → Usage Finalize            │
└──────────────┬───────────────────────────┬─────────────────┘
               │                           │ usage event
               ▼                           ▼
        Amazon Bedrock                Redis → 집계 → PostgreSQL
                                                    ▲
┌────────────────────── CONTROL PLANE ───────────────┼───────┐
│ Admin (browser) → frontend (Next.js SSR) → backend ┘       │
│   팀/사용자/키/모델/정책 CRUD, 대시보드·리더보드 조회        │
│   정책 변경 시 Redis 캐시 invalidate (값은 쓰지 않음)        │
└────────────────────────────────────────────────────────────┘
```

- gateway는 backend의 HTTP API를 호출하지 않습니다. 두 plane은 DB 스키마와 Redis 키 규약으로만 만납니다.
- gateway의 정책 조회 경로는 Redis → PostgreSQL이며, 요청 경로에서 DB 왕복이 없는 것을 목표로 합니다.

## Repository Layout

```text
llm-gateway/
├── backend/          admin 서비스 API (control plane, FastAPI)
├── frontend/         admin 콘솔 앱 (Next.js SSR)
├── gateway/          client API 진입점 (data plane, FastAPI proxy)
├── infra/
│   ├── chart/        Kubernetes 배포용 Helm chart
│   └── terraform/    AWS 클라우드 리소스 정의
├── docs/             설계 문서 및 ADR
└── docker-compose.yml  로컬 개발용 의존 스택
```

## Tech Stack

| 영역 | 선택 |
|---|---|
| Gateway (data plane) | Python + FastAPI (자체 구현) |
| Admin API (control plane) | Python + FastAPI, async SQLAlchemy, Alembic |
| Admin console | Next.js (App Router) + TypeScript, SSR |
| Model backend | AWS Bedrock |
| Database | PostgreSQL (Amazon RDS) |
| Cache / Queue | Redis (Amazon ElastiCache) |
| Compute | Kubernetes (Helm chart) |
| Infra as code | Helm + Terraform |
| Identity | 사내 SSO / IdP |

## Current Status

문서 기준선을 정리하고 구현을 시작하는 단계입니다. 각 컴포넌트는 별도 브랜치와 worktree에서
구현한 뒤 `main`으로 통합합니다.

| 컴포넌트 | 브랜치 | 상태 |
|---|---|---|
| backend | `feat/admin-backend` | 착수 예정 |
| gateway | `feat/gateway` | 착수 예정 |
| frontend | `feat/admin-frontend` | 착수 예정 |
| infra | `main` | 골격만 존재 |

진행 순서, 컴포넌트 간 계약, 미확정 결정 사항은
[implementation-plan.md](docs/implementation-plan.md)에 정의되어 있습니다.

## Documentation

| 문서 | 내용 |
|---|---|
| [implementation-plan.md](docs/implementation-plan.md) | 저장소 골격, 구현 순서, 브랜치 전략, 공유 계약 |
| [adr-0001](docs/adr-0001-self-hosted-data-plane.md) | LiteLLM 의존 제거와 gateway 자체 구현 결정 |
| [virtual-key-management.md](docs/virtual-key-management.md) | Virtual Key 수명주기와 감사 요구사항 |
| [usage-and-cost-observability.md](docs/usage-and-cost-observability.md) | 사용량 이벤트, 집계 축, 비용 추정 |
| [leaderboard-and-dashboard.md](docs/leaderboard-and-dashboard.md) | 대시보드 지표와 리더보드 요구사항 |
| [model-evaluation-playground.md](docs/model-evaluation-playground.md) | 모델 비교 실험 환경 |
| [adr-template.md](docs/adr-template.md) | 신규 ADR 작성 템플릿 |

## Local Development

로컬에서는 PostgreSQL과 Redis만 compose로 띄우고, 각 애플리케이션은 자기 디렉터리에서 실행합니다.

```bash
docker compose up -d
```

앱 서비스의 실행 방법과 compose 정의는 각 구현 브랜치에서 추가합니다.
