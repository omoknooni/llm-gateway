# 01. Client API 진입점

## Objective

client가 gateway에 요청을 보내는 표면(surface)을 정의합니다. OpenAI 호환과 Anthropic Messages
두 방언을 **동등하게** 노출하되, 방언이 파싱·직렬화 계층 밖으로 새지 않도록 내부 경계를 고정합니다.
근거는 [ADR-0003](../../docs/adr-0003-client-api-dialects.md)입니다.

방언 식별자는 backend의 `model.api_dialect` enum과 같은 값을 씁니다 — `OPENAI_CHAT`,
`ANTHROPIC_MESSAGES`. `usage_events.dialect`에 그대로 실리므로 다른 이름을 쓰면 집계가 갈립니다.

## Endpoints

| 메서드 | 경로 | 방언 | 인증 | 비고 |
|---|---|---|---|---|
| POST | `/v1/messages` | `ANTHROPIC_MESSAGES` | VK | 스트리밍 지원 |
| POST | `/v1/chat/completions` | `OPENAI_CHAT` | VK | 스트리밍 지원 |
| GET | `/v1/models` | `OPENAI_CHAT` | VK | VK 허용 범위로 **필터링** ([04](04-backend-routing.md)) |
| GET | `/v1/models/{model}` | `OPENAI_CHAT` | VK | 단일 모델 조회 |
| GET | `/healthz` | — | 면제 | liveness. 의존성 확인 없음 |
| GET | `/readyz` | — | 면제 | readiness. Redis/DB 상태 반영 |

- 인증 헤더는 두 방언 모두 `Authorization: Bearer vk_...`입니다. Anthropic client가 흔히 쓰는
  `x-api-key` 헤더도 VK 값으로 함께 수용합니다. 둘 다 있으면 `Authorization`이 우선입니다.
- 헬스 경로 이름은 backend(`/healthz`, `/readyz`)와 맞춥니다. 두 서비스의 프로브 설정이 같은
  모양이면 Helm 차트에서 실수할 여지가 줄어듭니다.
- Anthropic의 `/v1/messages/count_tokens`는 이번 범위에서 제외합니다. 필요해지면 provider의
  CountTokens를 그대로 태우는 얇은 경로로 추가합니다.

## Layering

```text
   HTTP 본문 (방언)
        │
        ▼
  DialectParser        방언 → NormalizedRequest.  미지원 필드는 여기서 거절.
        │
        ▼
  NormalizedRequest    provider도 방언도 모르는 단일 표현
        │
        ▼
  ProviderAdapter      NormalizedRequest → provider wire (05 문서)
        │
        ▼
  StreamEvent / ProviderResponse   provider 응답의 내부 표현
        │
        ▼
  DialectSerializer    내부 표현 → 방언 응답 본문 / SSE 프레임
```

방언 수 × provider 수가 곱해지지 않게 하는 구조입니다. 방언을 하나 더 붙일 때 건드리는 곳은
`dialects/`뿐이고, provider를 하나 더 붙일 때 건드리는 곳은 `providers/`뿐이어야 합니다.

```python
class DialectParser(Protocol):
    dialect: str                                # "OPENAI_CHAT" | "ANTHROPIC_MESSAGES"
    def parse(self, body: bytes) -> NormalizedRequest: ...

class DialectSerializer(Protocol):
    def response(self, r: ProviderResponse) -> bytes: ...
    def stream(self, events: AsyncIterator[StreamEvent]) -> AsyncIterator[bytes]: ...
    def error(self, err: GatewayError) -> tuple[int, bytes]: ...
```

## NormalizedRequest

```python
@dataclass(frozen=True)
class NormalizedRequest:
    model_alias: str                  # client가 지정한 alias (해석 전)
    messages: list[Message]
    system: list[ContentBlock] | None
    max_tokens: int
    stream: bool
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: ToolChoice | None = None
    reasoning: ReasoningSpec | None = None   # Anthropic thinking / OpenAI reasoning
    end_user_id: str | None = None           # 방언별 metadata에서 추출 (관측용, provider로 전달 안 함)
```

`ContentBlock`은 `text` / `image` / `tool_use` / `tool_result` / `thinking`을 가지며, Anthropic의
`cache_control`은 블록의 `cache_hint: bool`로 흡수합니다. OpenAI 방언은 대응 개념이 없어 항상
`False`입니다. 이 힌트는 provider adapter가 캐시 지원 여부를 보고 전달할 때만 씁니다.

> **단가는 캐시 TTL을 구분하지 않습니다.** `model.model_pricings`에는 `cache_write_price_per_1k`가
> 한 종류뿐입니다(5분/1시간 구분 없음). 요청이 어떤 TTL을 쓰든 write 토큰은 같은 단가로 계산합니다.
> Bedrock 온디맨드 기준선에서는 이 단순화가 맞고, 세분화가 필요해지면 backend에 단가 컬럼을
> 추가하는 것이 먼저입니다.

`end_user_id`(Anthropic `metadata.user_id`, OpenAI `user`)는 **파싱하되 provider로 전달하지
않습니다.** client가 채우는 값이라 신뢰할 수 없고, 같은 사람이 도구마다 다른 값을 보내면 provider
측 귀속이 흩어집니다. provider에 실리는 end-user 식별자는 gateway가 정합니다
([05](05-provider-invocation.md)의 "end-user 귀속"). 이 필드는 로그에만 남습니다.

**방언 고유 필드를 그대로 실어 나르는 통로(`extras`, `raw`)를 두지 않습니다.** 내부 표현이 흡수하지
못하는 필드는 통과시키는 대신 거절합니다. 통로를 하나 열면 방언이 adapter까지 새어 들어가고, 그때부터
"둘 중 하나는 사실 일급이 아닌" 구조가 됩니다.

## 필드 allow-list와 거절 규칙

미지원 필드는 조용히 무시하지 않고 **400 `unsupported_field`로 거절**합니다. 무시하면 client는
적용됐다고 오해하고, 그 오해가 비용과 품질 문제로 돌아옵니다
([ADR-0003](../../docs/adr-0003-client-api-dialects.md), 공유 계약 C6).

### Anthropic Messages (`/v1/messages`)

| 상태 | 필드 |
|---|---|
| 수용 | `model`, `messages`, `system`, `max_tokens`(필수), `stream`, `temperature`, `top_p`, `top_k`, `stop_sequences`, `tools`, `tool_choice`, `thinking`, `metadata.user_id` |
| 거절 | `service_tier`, `container`, `mcp_servers`, 그 외 미정의 최상위 필드 |

### OpenAI 호환 (`/v1/chat/completions`)

| 상태 | 필드 |
|---|---|
| 수용 | `model`, `messages`, `max_tokens` / `max_completion_tokens`, `stream`, `stream_options.include_usage`, `temperature`, `top_p`, `stop`, `tools`, `tool_choice`, `user`, `reasoning_effort` |
| 거절 | `n`(>1), `logit_bias`, `logprobs`, `top_logprobs`, `presence_penalty`, `frequency_penalty`, `seed`, `response_format`, `audio`, `modalities`, `web_search_options` |

- `n > 1`은 비용이 배수로 늘어나는데 정책 집행 단위는 요청 하나라 거절합니다. `n = 1`은 수용합니다.
- `max_tokens`가 없는 OpenAI 요청은 **`model_aliases.max_output_tokens`** 로 채웁니다. 그 값도
  NULL이면 설정의 기본값을 씁니다. Anthropic 방언은 스펙상 필수이므로 없으면 400입니다.
- `max_tokens`가 `max_output_tokens`를 넘으면 400으로 거절합니다. 잘라서 보내면 client는 잘린 줄
  모르고 응답이 짧은 이유를 모델 탓으로 돌립니다.
- 거절 메시지는 어떤 필드가 왜 거절됐는지 이름을 담습니다. `"Unsupported field: 'seed'"` 수준으로
  구체적이어야 client가 고칠 수 있습니다.

거절 목록은 코드의 상수 집합 하나에서 관리하고, 이 문서와 함께 갱신합니다. 두 곳에 흩어지면
곧 달라집니다.

## Streaming

내부 스트림 이벤트는 **블록 인덱스를 가진 Anthropic 계열 모양**을 기준으로 삼습니다. 블록 단위
이벤트에서 OpenAI의 delta chunk를 만들 수 있지만 그 반대는 손실 없이 되지 않기 때문입니다.

```python
StreamStart(response_id, model_alias)
ContentBlockStart(index, block_type)
ContentDelta(index, text | partial_json | thinking)
ContentBlockStop(index)
MessageDelta(stop_reason, usage_partial)
StreamEnd(usage)
StreamError(error)
```

| 방언 | 프레이밍 |
|---|---|
| `ANTHROPIC_MESSAGES` | `event: <type>` + `data: <json>`. `message_start` … `message_stop` 순서를 스펙대로 유지 |
| `OPENAI_CHAT` | `data: {chat.completion.chunk}` 반복 후 `data: [DONE]`. `stream_options.include_usage`가 참이면 마지막 usage chunk 추가 |

운영상 지켜야 하는 것들:

- **idle timeout** — 청크 간 무응답 상한을 두고, 초과 시 방언에 맞는 에러 프레임을 보내고 종료합니다.
  이 값은 반드시 앞단 ALB의 idle timeout보다 **작아야** 합니다. 크면 ALB가 먼저 끊어 client는
  깔끔한 에러 대신 잘린 스트림을 봅니다. 첫 토큰까지 60초를 넘기는 모델(extended thinking)이 있으므로
  너무 짧게 잡아도 정상 응답을 끊습니다. 기본값은 240초로 두고 환경별로 조정합니다.
- **client 끊김** — client가 연결을 끊어도 이미 발생한 비용은 존재합니다. 짧은 상한(기본 30초) 동안
  upstream을 계속 소비해 usage를 확정한 뒤 기록합니다.
- **usage 확정 실패** — provider가 usage를 주지 않고 끝난 경우 누적 텍스트로 출력 토큰을 역산하고
  `usage_events.estimated_usage = true`로 표시합니다. 0으로 기록하지 않습니다.
- 스트림 도중 실패는 이미 200 헤더가 나간 뒤이므로 HTTP 상태로 표현할 수 없습니다. 반드시
  **스트림 안의 에러 프레임**으로 전달하고, `usage_events.status`는 `ERROR`로 기록합니다.

## Error Mapping

내부 오류 코드는 공유 계약 C6이 정의합니다. 이 코드가 두 방언의 형식으로 옮겨지고,
동시에 `usage_events.error_code` / `auth_events.outcome`에 그대로 실립니다. 표현만 바꾸고
구분은 유지합니다.

| 내부 코드 (C6) | HTTP | Anthropic `error.type` | OpenAI `error.type` | 기록 위치 |
|---|---|---|---|---|
| `invalid_virtual_key` | 401 | `authentication_error` | `authentication_error` | `auth_events` |
| `model_not_allowed` | 403 | `permission_error` | `permission_error` | `auth_events` |
| `model_inactive` | 404 | `not_found_error` | `invalid_request_error` (`code: model_not_found`) | `auth_events` |
| `budget_exceeded` | 429 | `rate_limit_error` | `rate_limit_error` | `auth_events` |
| `rate_limit_exceeded` | 429 | `rate_limit_error` | `rate_limit_error` | `auth_events` |
| `dialect_not_supported` | 400 | `invalid_request_error` | `invalid_request_error` | 기록 없음 |
| `unsupported_field` | 400 | `invalid_request_error` | `invalid_request_error` | 기록 없음 |
| `invalid_request` | 400 | `invalid_request_error` | `invalid_request_error` | 기록 없음 |
| `request_too_large` | 413 | `request_too_large` | `invalid_request_error` | 기록 없음 |
| `provider_error` | 502 | `api_error` | `server_error` | `usage_events` (`ERROR`) |
| `upstream_timeout` | 504 | `api_error` | `server_error` | `usage_events` (`TIMEOUT`) |
| `dependency_unavailable` | 503 | `overloaded_error` | `server_error` | 기록 없음 |

- 429는 `Retry-After` 헤더를 함께 보냅니다(C6).
- **기록 위치의 원칙**: provider 호출이 일어났으면 `usage_events`, 정책이 막았으면 `auth_events`,
  요청 자체가 잘못됐으면 기록하지 않고 로그·메트릭만 남깁니다. 잘못된 요청까지 DB에 남기면
  client 버그 하나가 테이블을 채웁니다.
- `dialect_not_supported`는 정책 거절이 아니라 **잘못된 엔드포인트로 보낸 요청**이므로 기록하지
  않습니다. `auth_events.outcome`의 값 집합이 backend의 [09](../../backend/docs/09-gateway-contract-response.md)
  표와 정확히 일치하게 하는 판단이기도 합니다 ([06](06-contract-response.md) S4 확인 사항).

본문 형식:

```jsonc
// Anthropic
{"type": "error", "error": {"type": "permission_error", "message": "..."}}

// OpenAI
{"error": {"message": "...", "type": "permission_error", "param": null, "code": "model_not_allowed"}}
```

- provider의 원문 오류 메시지를 그대로 client에 노출하지 않습니다. 계정 ID·ARN·내부 엔드포인트가
  섞여 나옵니다. client에는 분류된 메시지를, 로그에는 원문을 남깁니다.
- 모든 응답에 `x-request-id`를 실어 로그·`usage_events.request_id`와 대조할 수 있게 합니다.

## Request Limits

| 항목 | 기본값 | 근거 |
|---|---|---|
| 요청 본문 최대 크기 | 20 MB | 이미지 블록 포함 요청 수용. 초과 시 413 |
| non-stream 응답 대기 | 300s | 긴 추론 수용 |
| 스트림 idle 상한 | 240s | ALB idle timeout보다 작아야 함 |
| 끊김 후 drain 상한 | 30s | 과금 정확도 확보 |

## 테스트 기준

- 두 방언 각각: non-stream 성공, stream 성공, 거절 필드 400, 모델 미등록 404, 인증 실패 401
- 동일한 논리적 요청을 두 방언으로 보냈을 때 **같은 `usage_events` 행 내용**이 나오는지
  (`dialect` 컬럼만 다름)
- SSE 프레임 순서가 각 방언 스펙을 만족하는지 (Anthropic 이벤트 순서, OpenAI `[DONE]` 종결)
- 스트림 중간 실패가 HTTP 200 + 에러 프레임 + `status=ERROR` 기록으로 나오는지
- C6 코드마다 두 방언의 HTTP 상태·`error.type`이 표와 일치하는지 (테이블 주도)
- 각 오류의 기록 위치가 표와 일치하는지 (`usage_events` / `auth_events` / 기록 없음)
- `max_tokens` 미지정 시 `max_output_tokens`로 채워지고, 초과 시 400
