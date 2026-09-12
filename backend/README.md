# backend — Admin API (control plane)

Admin 서비스의 API. 팀/사용자/Virtual Key/모델 카탈로그/정책·예산의 **source of truth**이며,
사용량 집계 조회 API를 `frontend/`에 제공합니다. client의 추론 요청은 받지 않습니다.

- 스택: Python + FastAPI, async SQLAlchemy, Alembic, PostgreSQL, Redis
- 작업 브랜치: `feat/admin-backend`
- 기준 문서: [docs/implementation-plan.md](../docs/implementation-plan.md)
- 구현 계획: [backend/docs/](docs/) — 읽는 순서는 [docs/README.md](docs/README.md)

## 구조

```text
backend/
├── src/app/
│   ├── main.py          FastAPI 조립, lifespan, 예외 핸들러, 미들웨어
│   ├── core/            설정, DB/Redis, 인증, 감사, 캐시 무효화, 예외
│   ├── models/          SQLAlchemy ORM (스키마 정의의 원천)
│   ├── schemas/         Pydantic 요청/응답 DTO
│   ├── repositories/    쿼리 계층
│   ├── services/        도메인 규칙, 트랜잭션 경계
│   ├── routers/         HTTP 계층
│   └── jobs/            주기 작업
│   └── policy/          gateway 와 공유하는 판정 규칙 (순수 함수)
├── db/                  마이그레이션 컴포넌트 (앱과 분리)
└── tests/
```

## 로컬 실행

의존 스택(PostgreSQL, Redis)은 저장소 루트의 compose로 띄웁니다.

```bash
# 저장소 루트에서
docker compose up -d

# backend 디렉터리에서
uv venv && uv pip install -r pyproject.toml --extra dev
cp .env.example .env          # 값 채우기

# 스키마 적용 (마이그레이션은 DDL 권한을 가진 역할로)
MIGRATION_DATABASE_URL='postgresql+asyncpg://postgres:postgres@localhost:5432/llm_gateway' \
  ./db/run_migration.sh

# 앱 실행
PYTHONPATH=src .venv/bin/uvicorn app.main:app --reload --port 8080

# 주기 작업 (별도 프로세스. 만료 키 정리, 캐시 재시도, 단가 누락 점검,
#            예산 임계 감지, 예산 카운터 정합성 검증, 사용량 일·월 집계)
PYTHONPATH=src .venv/bin/python -m app.jobs.main
```

- OpenAPI 문서: <http://localhost:8080/docs> — 이 문서가 frontend와의 계약 원천입니다.
- 헬스: `GET /healthz`(생존), `GET /readyz`(DB·Redis 연결)

> 루트 `docker-compose.yml`에 backend 서비스를 추가하는 작업은 공용 파일 변경이므로
> `main` 브랜치에서 처리합니다(AGENTS.md 브랜치 규율).

## 검사

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest
```
