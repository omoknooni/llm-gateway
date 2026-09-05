# ADR-0003: client 인터페이스로 OpenAI 호환과 Anthropic Messages를 모두 지원

- Status: Accepted
- Date: 2026-09-06
- Decision Makers: llm-gateway owner

## Context

`gateway`가 client에게 어떤 요청/응답 형식(dialect)을 제공할지 미확정이었습니다.
gateway를 자체 구현하기로 한 이상([ADR-0001](adr-0001-self-hosted-data-plane.md)) 이 범위는
직접 구현하고 유지해야 하는 분량을 그대로 결정합니다.

전제는 두 가지입니다.

- **client는 Claude만 쓰지 않습니다.** Bedrock에는 Claude 외의 모델도 있고, 사내 client가 이들을
  함께 쓸 수 있어야 합니다. 즉 Claude 전용 형식만 노출하면 다른 모델을 표준 경로로 태울 수 없습니다.
- **Claude 네이티브 client가 존재합니다.** Anthropic Messages 형식을 그대로 보내는 도구들은
  OpenAI 형식으로 변환해 주지 않습니다. 이들을 받으려면 Messages 엔드포인트가 필요합니다.

한쪽만 고르면 둘 중 하나의 client 군을 버리거나, 각 client 쪽에 변환 계층을 떠넘기게 됩니다.
변환을 client가 하면 사내에 같은 변환 코드가 팀 수만큼 생깁니다.

## Decision

gateway는 **OpenAI 호환과 Anthropic Messages 두 방언을 모두 지원**합니다.

- 공개 엔드포인트는 두 계열입니다.
  - OpenAI 호환: `/v1/chat/completions`, `/v1/models`
  - Anthropic Messages: `/v1/messages`
- 두 방언은 **동등한 시민**입니다. 한쪽을 다른 쪽으로 변환해 내보내는 종속 관계를 만들지 않습니다.
- 내부적으로는 요청을 **정규화된 내부 표현**으로 변환한 뒤 provider adapter가 Bedrock 호출로 옮깁니다.
  방언 수와 provider 수가 곱해지지 않도록 `dialect → 내부 표현 → provider` 구조를 유지합니다.
- 인증(Virtual Key), 정책 집행, 사용량 이벤트 발행은 **방언과 무관하게 동일한 경로**를 지납니다.
  방언은 요청 파싱과 응답 직렬화 계층에만 존재합니다.
- 두 방언 모두 스트리밍을 지원합니다. 각 방언이 규정한 스트림 형식(SSE 이벤트 종류와 순서)을 따릅니다.
- 지원하지 않는 필드는 조용히 무시하지 않고 **명시적으로 거절**합니다. 무시하면 client가
  적용됐다고 오해하고, 그 오해가 비용과 품질 문제로 돌아옵니다.

## Consequences

### Positive

- Claude 네이티브 client와 OpenAI SDK 기반 client를 모두 코드 수정 없이 수용합니다.
- 모델 선택이 client 형식에 묶이지 않습니다. 어떤 방언으로 들어와도 허용된 모델 alias를 쓸 수 있습니다.
- 변환 코드가 gateway 한 곳에만 존재하므로 팀별 중복 구현이 사라집니다.
- 인증·집행·과금이 단일 경로라 방언이 늘어도 정책 집행에 구멍이 생기지 않습니다.

### Negative

- 파싱·직렬화·스트림 처리·에러 매핑을 두 벌 구현하고 유지해야 합니다.
- 두 방언의 스펙 변화를 각각 따라가야 합니다.
- 방언 간 표현력 차이(한쪽에만 있는 기능)를 내부 표현이 흡수해야 하고, 흡수 불가한 부분은
  거절 규칙으로 관리해야 합니다.

### Follow-up Implications

- 각 방언별로 **지원 필드 allow-list**를 명시하고 문서화해야 합니다. 미지원 필드의 거절 응답 형식도
  방언 규약에 맞춰야 합니다.
- 토큰 사용량은 provider 응답값을 우선 사용합니다. 방언에 따라 사용량 필드 이름과 위치가 다르므로,
  사용량 이벤트 스키마는 방언 중립적으로 정의합니다.
- 에러 매핑 표가 필요합니다. 인증 실패 / 정책 거절 / provider 오류를 각 방언의 오류 형식으로
  옮기되, 내부 오류 타입 구분은 유지합니다.
- Claude 외 모델을 어느 방언으로 노출할지는 모델 카탈로그의 속성으로 다룹니다.
  모델별로 지원 방언이 다를 수 있습니다.
- 우선순위: 두 방언을 동시에 완성하지 않아도 됩니다. 내부 표현과 adapter 경계를 먼저 세우고
  방언을 순차적으로 붙입니다.

## Options

### 1. OpenAI 호환만 지원

`/v1/chat/completions` 하나만 노출하고 Claude도 이 형식으로 감쌉니다.

- 장점
  - 구현·유지 분량이 가장 적고, OpenAI SDK 생태계를 그대로 씁니다.
  - 모델 간 인터페이스가 강제로 통일됩니다.
- 단점
  - Anthropic Messages를 보내는 Claude 네이티브 client를 받을 수 없습니다.
  - Messages 스펙에만 있는 기능이 OpenAI 스키마로 표현되지 않아 손실됩니다.
- 선택하지 않은 이유
  - Claude 네이티브 client 군을 버리거나, 각 client에 변환 부담을 떠넘기게 됩니다.

### 2. Anthropic Messages만 지원

`/v1/messages` 하나만 노출합니다.

- 장점
  - Claude 계열 기능을 손실 없이 노출합니다.
- 단점
  - Claude 외 모델을 Claude 형식에 억지로 맞춰야 합니다.
  - OpenAI SDK 기반 client가 전부 변환을 직접 해야 합니다.
- 선택하지 않은 이유
  - client가 Claude 외 모델도 쓸 것이라는 전제와 정면으로 어긋납니다.

### 3. 두 방언 모두 지원

두 계열 엔드포인트를 노출하고 내부 표현으로 수렴시킵니다.

- 장점
  - 두 client 군을 모두 수용하고 모델 선택이 형식에 묶이지 않습니다.
- 단점
  - 구현·유지 분량이 늘어납니다.
- 선택하지 않은 이유
  - 해당 없음
- 최종 선택 여부: Accepted

## References

- [ADR-0001: gateway 자체 구현](adr-0001-self-hosted-data-plane.md)
- [docs/implementation-plan.md](implementation-plan.md)
- [docs/usage-and-cost-observability.md](usage-and-cost-observability.md)
