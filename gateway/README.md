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
