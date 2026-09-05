# backend — Admin API (control plane)

Admin 서비스의 API. 팀/사용자/Virtual Key/모델 카탈로그/정책·예산의 **source of truth**이며,
사용량 집계 조회 API를 `frontend/`에 제공합니다. client의 추론 요청은 받지 않습니다.

- 스택: Python + FastAPI, async SQLAlchemy, Alembic, PostgreSQL, Redis
- 작업 브랜치: `feat/admin-backend`
- 기준 문서: [docs/implementation-plan.md](../docs/implementation-plan.md)
