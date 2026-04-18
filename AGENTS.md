# AGENTS.md

## Repository Context

이 저장소는 LiteLLM 기반 사내 LLM Gateway와 중앙 비용 관제 플랫폼을 설계하고 구현하기 위한 작업 공간입니다. 현재 단계는 문서 우선 스캐폴드이며, 구현 전 아키텍처 방향, 기능 경계, 운영 원칙을 먼저 정리합니다.

## Default Technical Direction

- Gateway: LiteLLM with OpenAI-compatible interface
- Management API: Python + FastAPI
- Model backend: AWS Bedrock
- Data layer: PostgreSQL + Redis
- Ops dashboard: Next.js + TypeScript
- Identity source: corporate SSO / IdP
- Cost estimation baseline: Bedrock on-demand pricing

## Working Principles

- 실제 Bedrock 자격 증명은 외부에 노출하지 않고 Virtual Key만 발급합니다.
- 팀/사용자/Virtual Key/모델 축으로 사용량과 추정 비용이 집계되어야 합니다.
- 운영 Gateway와 모델 비교 실험 환경은 논리적으로 분리된 구조를 전제로 합니다.
- 세부 기능 설계는 이 파일에 길게 적지 않고 `docs/` 하위 instruction 문서를 기준으로 확장합니다.

## Read These Docs First

- [docs/gateway-architecture.md](docs/gateway-architecture.md)
- [docs/virtual-key-management.md](docs/virtual-key-management.md)
- [docs/usage-and-cost-observability.md](docs/usage-and-cost-observability.md)
- [docs/model-evaluation-playground.md](docs/model-evaluation-playground.md)
- [docs/leaderboard-and-dashboard.md](docs/leaderboard-and-dashboard.md)
- [docs/deployment-and-operations.md](docs/deployment-and-operations.md)

## Expected Output Style

- README는 프로젝트 개요와 전체 구조를 설명합니다.
- `docs/` 문서는 기능별 instruction과 구현 기준을 설명합니다.
- 구현 시에는 문서에 나온 엔터티 이름과 책임 경계를 우선 유지합니다.
