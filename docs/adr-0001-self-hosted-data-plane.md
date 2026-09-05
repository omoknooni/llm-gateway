# ADR-0001: LiteLLM 의존을 제거하고 gateway를 자체 구현

- Status: Accepted
- Date: 2026-09-06
- Decision Makers: llm-gateway owner

## Context

초기 기준선은 LiteLLM Proxy를 data plane으로 두고, 그 위에 admin control plane을 wrapper 형태로
얹는 구조였습니다. 실제로 진행하면서 아래 문제가 드러났습니다.

- 정책의 source of truth가 LiteLLM 내부 DB와 사내 DB로 이원화되어, 둘을 맞추는 reconcile 계층이
  영구 부채가 됩니다. Virtual Key 하나를 발급해도 두 곳에 써야 하고, 한쪽이 실패하면 상태가 갈라집니다.
- LiteLLM이 남기는 사용량 로그로는 이 프로젝트가 요구하는 관측 축(cache token 구분, TTFT,
  모델 다운그레이드 이력, 호출 client 차원)을 채울 수 없습니다.
- 예산 초과 차단, 모델 다운그레이드, 팀별 rate limit 같은 집행 규칙을 요청 경로에 넣으려면
  결국 LiteLLM 앞에 프록시를 하나 더 둬야 합니다.
- 서드파티 버전 업그레이드가 인증·과금 경로의 리스크가 됩니다.

한편 필요한 기능 범위(호환 인터페이스 + Bedrock 호출 + 정책 집행 + 사용량 기록)는 참조 구현
`awsome-ai-gateway`가 보여주듯 자체 구현이 현실적인 규모입니다.

## Decision

LiteLLM 의존을 제거하고 **control plane과 data plane을 모두 자체 구현**합니다.

- `gateway/`는 FastAPI 기반 자체 프록시로 구현하며, client 요청 인증부터 Bedrock 호출,
  사용량 이벤트 발행까지 요청 경로 전체를 소유합니다.
- `backend/`는 정책의 유일한 source of truth이며, 외부 제품 DB와의 동기화 계층을 두지 않습니다.
- 참조 구현의 컴포넌트 분리(control plane / data plane / 비용 기록)는 차용하되, 코드를 그대로
  가져오지 않고 이 저장소 문서에 정의된 엔터티와 책임 경계를 따릅니다.

## Consequences

### Positive

- 정책 상태가 한 곳에만 존재하므로 reconcile 계층과 그로 인한 장애 모드가 사라집니다.
- 요청 경로 미들웨어를 직접 정의하므로 예산·rate limit·다운그레이드 집행 위치를 통제할 수 있습니다.
- 사용량 이벤트 스키마를 직접 설계하므로 관측 요구사항을 스키마 수준에서 충족할 수 있습니다.
- 서드파티 릴리스 주기가 인증·과금 경로의 리스크에서 빠집니다.

### Negative

- 호환 인터페이스, 스트리밍, 에러 매핑, 토큰 카운팅을 직접 구현하고 유지해야 합니다.
- 새 모델·새 파라미터 지원이 자동으로 따라오지 않고 작업량이 됩니다.
- 초기 구현 분량이 wrapper 방식보다 큽니다.

### Follow-up Implications

- 지원하는 요청/응답 방언(dialect)의 범위를 명시하고, 미지원 필드는 명확히 거절해야 합니다.
- 토큰 사용량은 provider 응답값을 우선 사용하고, 없을 때의 추정 방식을 별도로 정의해야 합니다.
- provider 추상화를 유지해 향후 비 Bedrock 확장 여지를 남깁니다.
- LiteLLM 전제 구현물과 문서는 존치가 아니라 제거 대상입니다(선행 커밋에서 정리).

## Options

### 1. LiteLLM + wrapper control plane

LiteLLM Proxy를 그대로 쓰고 관리 기능만 자체 API로 감쌉니다.

- 장점
  - 초기 구현량이 가장 적고, 모델 지원과 호환 인터페이스를 무료로 얻습니다.
- 단점
  - 정책 원천 이원화와 reconcile 부채가 발생합니다.
  - 사용량 로그 스키마를 바꿀 수 없습니다.
  - 집행 로직을 넣으려면 결국 프록시를 하나 더 둬야 합니다.
- 선택하지 않은 이유
  - 이 프로젝트의 핵심 가치가 인증·집행·비용 관제인데, 그 셋이 모두 통제 밖에 놓입니다.

### 2. gateway 자체 구현

gateway를 직접 구현하고 LiteLLM을 제거합니다.

- 장점
  - 정책·집행·관측을 한 스키마 안에서 일관되게 다룹니다.
- 단점
  - 호환 인터페이스와 모델 지원 유지 비용을 직접 집니다.
- 선택하지 않은 이유
  - 해당 없음
- 최종 선택 여부: Accepted

### 3. 상용 LLM gateway 제품 도입

외부 상용 제품을 구매해 운영합니다.

- 장점
  - 운영 부담이 가장 낮습니다.
- 단점
  - 사내 SSO/팀 구조와 비용 정산 요구에 맞추려면 결국 커스터마이즈가 필요합니다.
  - 호출 메타데이터가 외부 제품 경계 안에 갇힙니다.
- 선택하지 않은 이유
  - 사내 비용 관제라는 목표 대비 통제권과 데이터 소유권이 부족합니다.

## References

- [docs/implementation-plan.md](implementation-plan.md)
- [docs/usage-and-cost-observability.md](usage-and-cost-observability.md)
- [docs/virtual-key-management.md](virtual-key-management.md)
- 참조 구현: `awsome-ai-gateway` (admin-api / admin-ui / gateway-proxy / cost-recorder-worker)
