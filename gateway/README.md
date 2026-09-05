# gateway — Client API 진입점 (data plane)

client의 API 진입점. Virtual Key 인증, 정책 집행, Bedrock 호출 프록시, 사용량 이벤트 발행을
담당합니다. 정책을 소유하지 않고 읽어서 집행만 합니다.

- 스택: Python + FastAPI (자체 구현, 서드파티 proxy 제품 미사용)
- 작업 브랜치: `feat/gateway`
- 기준 문서: [docs/implementation-plan.md](../docs/implementation-plan.md)
