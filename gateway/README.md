# gateway — Client API 진입점 (data plane)

client의 API 진입점. Virtual Key 인증, 정책 집행, Bedrock 호출 프록시, 사용량 이벤트 발행을
담당합니다. 정책을 소유하지 않고 읽어서 집행만 합니다.

- 스택: Python + FastAPI (자체 구현, 서드파티 proxy 제품 미사용)
- 방언: OpenAI 호환(`/v1/chat/completions`)과 Anthropic Messages(`/v1/messages`) 동시 지원
- 백엔드: Amazon Bedrock (boto3) / Bedrock Mantle (HTTPS + bearer)
- 작업 브랜치: `feat/gateway`
- 기준 문서: [docs/implementation-plan.md](../docs/implementation-plan.md), backend `docs/08-shared-contracts.md`

## 설계 문서

구현 착수 전에 확정한 계획입니다. 시작점은 [docs/README.md](docs/README.md)입니다.

| 문서 | 범위 |
|---|---|
| [docs/README.md](docs/README.md) | 요청 파이프라인, 모듈 구조, backend 공유 계약 합의 결과, 구현 순서 |
| [docs/01-api-entrypoint.md](docs/01-api-entrypoint.md) | 두 방언, 내부 표현, 스트리밍, 에러 매핑 |
| [docs/02-virtual-key-auth.md](docs/02-virtual-key-auth.md) | VK 인증, 허용 모델 3층 해석, 캐시 소유권 |
| [docs/03-client-identification.md](docs/03-client-identification.md) | client 식별, 신뢰 경계 |
| [docs/04-backend-routing.md](docs/04-backend-routing.md) | 모델 alias 해석, 리전, provider 선택 |
| [docs/05-provider-invocation.md](docs/05-provider-invocation.md) | Bedrock / Mantle adapter, 자격 증명 |
| [docs/06-contract-response.md](docs/06-contract-response.md) | backend 회신(Q1~Q5)에 대한 답변과 확정 사항 |

## 실행

의존 스택(PostgreSQL / Redis)은 저장소 루트의 compose 로 띄우고, 앱은 이 디렉터리에서 실행합니다.

```bash
uv venv --python 3.11 .venv
uv pip install -e ".[dev]"

cp .env.example .env          # DATABASE_URL 은 gateway_app 역할입니다
.venv/bin/uvicorn gateway.main:app --reload --port 8000
```

```bash
.venv/bin/python -m pytest      # 단위 + 스택 테스트 (외부 의존성 없이 동작)
.venv/bin/python -m ruff check src tests
```

- 스키마 마이그레이션은 backend 가 소유합니다. 이 패키지에 Alembic 이 없는 것은 의도입니다.
- AWS 자격 증명은 기본 credential chain 에서 옵니다 — 운영은 IRSA, 로컬은 개발자 프로필.
  `.env` 에 액세스 키를 두지 않습니다.

## 구현 현황

| 단계 | 내용 | 상태 |
|---|---|---|
| M1 | 골격 — 설정, 로깅, DB/Redis, 프로브, pure ASGI 미들웨어 | 완료 |
| M2 | VK 인증, 허용 모델 3층 해석, client 식별 | 완료 |
| M3 | 모델 카탈로그 해석, 리전 접두사 재작성 | 완료 |
| M4 | 내부 표현, Anthropic Messages 방언, Bedrock 호출 | 완료 |
| M5 | OpenAI 호환 방언, usage / auth 이벤트 기록 | 완료 |
| M6 | Mantle adapter | 완료 (backend 의 S1·S2 마이그레이션 적용 후 사용 가능) |

**남은 것**: 실제 PostgreSQL·Redis·Bedrock 을 붙인 통합 테스트, Phase 4(예산·rate limit 집행).
현재 테스트는 외부 의존성 없이 도는 범위까지입니다.
