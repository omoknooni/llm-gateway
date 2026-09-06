# 05. Bedrock / Mantle 호출

## Objective

`BackendDecision`을 실제 모델 호출로 옮깁니다. 이 계층은 **방언을 모릅니다** — `NormalizedRequest`를
받아 provider의 wire 형식으로 직렬화하고, 응답을 내부 표현(`ProviderResponse` / `StreamEvent`)으로
되돌립니다.

두 백엔드는 전송 방식부터 다릅니다.

| | Bedrock (native) | Bedrock Mantle |
|---|---|---|
| `model.provider` 값 | `BEDROCK` | `BEDROCK_MANTLE` (**S1: 추가 요청 중**) |
| 전송 | boto3 `bedrock-runtime` (동기, SigV4) | HTTPS + Bearer 토큰 (async httpx) |
| 엔드포인트 | AWS SDK가 해석 | `model_aliases.endpoint_url` (**S2: 추가 요청 중**) |
| 본문 | Bedrock native (`anthropic_version` 포함) | 표준 Anthropic Messages |
| 자격 증명 | IRSA credential chain | IRSA 자격 → 단기 bearer |
| IAM 네임스페이스 | `bedrock:*` | **`bedrock-mantle:*`** |

마지막 줄은 실전에서 가장 많이 틀리는 지점입니다. Mantle은 `bedrock:`이 아니라 **별개의
`bedrock-mantle:` 서비스 네임스페이스**를 씁니다. `bedrock:InvokeModel`만 준 role로 Mantle을 부르면
403이 납니다.

> **Mantle은 M6입니다.** backend 스키마에 S1(enum 값)과 S2(endpoint 컬럼)가 반영되기 전에는
> Mantle 모델을 카탈로그에 등록할 수 없습니다. 그전까지는 Bedrock native만 구현하고, adapter
> 경계와 registry는 지금 세워 둡니다. 두 항목의 상세는 [docs/README.md](README.md)의
> "backend에 요청하는 스키마 변경"에 있습니다.

## ProviderAdapter

```python
class ProviderAdapter(ABC):
    @abstractmethod
    async def invoke(
        self, req: NormalizedRequest, decision: BackendDecision
    ) -> ProviderResponse: ...

    @abstractmethod
    async def invoke_stream(
        self, req: NormalizedRequest, decision: BackendDecision
    ) -> tuple[int, AsyncIterator[StreamEvent]]: ...
```

```python
@dataclass
class ProviderResponse:
    status: int
    content: list[ContentBlock]
    stop_reason: str | None
    usage: TokenUsage
    upstream_request_id: str | None    # 장애 시 AWS에 문의할 때 쓰는 값
```

- adapter는 `ProviderRegistry`에 `Provider` enum으로 등록되고, 라우터는
  `registry.get(decision.provider)` 하나로 꺼내 씁니다. 라우터에 provider별 `if`가 생기면
  이 설계는 실패한 것입니다.
- **adapter는 `BackendDecision`만 받습니다.** 리전·엔드포인트·모델 ID가 전부 거기 들어 있으므로
  adapter가 설정이나 DB를 다시 읽을 일이 없습니다.
- `invoke_stream`은 **상태 코드를 먼저 확정한 뒤** 이터레이터를 돌려줍니다. 스트림을 열어보지도 않고
  200을 반환하면 upstream 4xx/5xx가 "200 + 본문 속 에러"로 둔갑해 client가 실패를 성공으로 처리합니다.
- adapter는 usage를 기록하지 않습니다. `TokenUsage`를 채워 돌려주기만 하고, 기록은 라우터의
  finalize 단계가 합니다. 성공·실패·중단이 모두 한 자리를 지나야 누락이 없습니다.

## 자격 증명 원칙

[implementation-plan.md](../../docs/implementation-plan.md)의 배포 기준선을 그대로 따릅니다.

- **장기 AWS 액세스 키를 이미지·코드·Secret에 두지 않습니다.** 자격 증명 획득은 기본 credential
  chain에 위임합니다. 운영은 IRSA, 로컬은 개발자 AWS 프로필이 같은 코드로 동작합니다.
- 코드에 CSP별·환경별 분기를 두지 않습니다. 환경 차이는 설정값(리전)으로만 표현합니다.
- **cross-account 호출은 이번 범위 밖입니다.** 대상 계정의 role ARN을 둘 자리가 backend 스키마에
  없습니다(참조 구현은 `routing_profiles`에 뒀지만 우리는 그 테이블을 만들지 않습니다 —
  [04](04-backend-routing.md)). 필요해지면 "role ARN을 어느 테이블의 어느 컬럼에 둘 것인가"부터
  ADR로 정합니다. 그전까지 Bedrock도 Mantle도 **in-account(pod의 IRSA)** 로만 나갑니다.

## end-user 귀속

두 adapter 모두 요청 본문의 `metadata.user_id`에 **gateway가 정한 불투명 식별자**를 채웁니다.
provider 측 남용 탐지가 "같은 사람의 연속 호출"을 묶을 수 있게 하기 위한 값입니다.

```text
metadata.user_id = auth_context.user_id        (owner_type = USER)
                 = auth_context.virtual_key_id (owner_type = TEAM — 귀속될 사람이 없음)
```

- **client가 보낸 값을 그대로 쓰지 않습니다.** `NormalizedRequest.end_user_id`는 관측용으로만
  남고 provider로 나가지 않습니다 ([01](01-api-entrypoint.md)).
- **`idp_subject`(OIDC `sub`)를 쓰지 않습니다.** provider가 요구하는 것은 불투명 식별자인데,
  IdP 설정에 따라 `sub`에 이메일이나 사번이 그대로 들어올 수 있습니다. 상세는
  [06](06-contract-response.md) Q4.
- VK id가 아니라 사용자 id를 우선하는 이유는 **로테이션 내성**입니다. VK는 주기적으로 교체되지만
  사람은 그대로이므로, VK id를 쓰면 로테이션마다 provider 측 추적이 끊깁니다.
- 두 값 모두 UUID라 provider 쪽에서 역추적할 수 없고, 우리 DB에서는 그대로 조인됩니다.

## Bedrock adapter

### 클라이언트 구성

```python
boto3.client(
    "bedrock-runtime",
    region_name=decision.region,                   # model_aliases.region ?? 배포 기본값
    config=BotoConfig(
        max_pool_connections=50,
        connect_timeout=10,
        read_timeout=settings.stream_timeout,      # 스트림과 공유하므로 길게
        retries={"total_max_attempts": 1, "mode": "standard"},
    ),
)
```

- **재시도를 끕니다(`total_max_attempts=1`).** botocore 기본값은 최대 5회까지 재시도하는데,
  gateway가 위에서 자체 재시도를 붙이면 두 값이 곱해져 장애 시 요청 폭풍이 됩니다.
  재시도 정책의 소유자는 gateway 하나여야 합니다.
- `read_timeout`은 스트리밍 호출과 같은 클라이언트를 쓰므로 긴 값(기본 300초)을 유지합니다.
  짧게 잡으면 정상적인 긴 스트림이 끊깁니다.
- 클라이언트는 **리전별로 하나씩 만들어 캐시**합니다. `model_aliases.region`이 모델마다 다를 수
  있으므로 요청마다 만들면 커넥션 풀이 매번 새로 생깁니다.

### 동기 클라이언트를 async에서 쓰기

boto3는 동기입니다. 이벤트 루프에서 직접 호출하면 워커 전체가 멈춥니다.

- 호출과 이벤트 스트림 순회를 **전용 `ThreadPoolExecutor`** 에서 실행합니다.
  기본 executor를 쓰면 다른 블로킹 작업과 스레드를 다투게 됩니다.
- 풀 크기는 동시 스트림 수의 상한이 됩니다. `max_pool_connections`와 함께 맞춰 잡습니다.
- 스트리밍 응답의 `next()` 한 번 한 번이 네트워크 대기이므로, 순회 전체를 executor에 넘깁니다.

```text
invoke:        client.invoke_model(modelId, body, contentType, accept)
invoke_stream: client.invoke_model_with_response_stream(...) → EventStream
               각 event["chunk"]["bytes"] = Anthropic SSE 이벤트 1건의 JSON
```

`Converse` API 대신 `InvokeModel`을 씁니다. Anthropic Messages 방언이 Bedrock native 본문과 거의
1:1이라 변환 손실이 가장 적고, `cache_control`·`thinking` 같은 모델 고유 필드가 그대로 지나가기
때문입니다. 모델군이 늘어 공통 표면이 필요해지면 그때 `Converse` adapter를 **추가**합니다.

### 오류 매핑

`ClientError`의 AWS 오류 코드를 내부 코드(C6)로 옮깁니다.

| AWS 코드 | 내부 코드 | HTTP |
|---|---|---|
| `ValidationException` | `invalid_request` | 400 |
| `AccessDeniedException` | `provider_error` | 502 |
| `ResourceNotFoundException` | `model_inactive` | 404 |
| `ThrottlingException` | `rate_limit_exceeded` | 429 |
| `ModelTimeoutException` | `upstream_timeout` | 504 |
| `ServiceException` · `InternalServerException` | `provider_error` | 502 |
| 그 외 | `provider_error` | 502 |

- **`AccessDeniedException`을 403으로 넘기지 않습니다.** 이건 client의 권한 문제가 아니라
  gateway의 IAM 설정 문제입니다. 403으로 주면 client가 자기 키를 의심하며 시간을 씁니다.
  502로 주고 로그에 원인을 정확히 남깁니다.
- provider 호출이 시작된 뒤의 실패이므로 이 오류들은 **`usage_events`에 기록**됩니다
  (`status = ERROR` 또는 `TIMEOUT`, `error_code`에 위 코드). 토큰은 대개 0이지만 행은 남습니다 —
  "실패도 운영 관점에서는 중요한 신호"라는 관측 요구사항 그대로입니다.
- `ThrottlingException`으로 인한 429는 우리 rate limit이 아니라 **upstream의 429**입니다.
  `auth_events`가 아니라 `usage_events`로 가는 이유가 이것입니다. 두 429를 구분하지 못하면
  "우리 한도를 올렸는데도 429가 준다"는 상황을 진단할 수 없습니다.

## Mantle adapter (M6)

### 호출

```text
POST {model_aliases.endpoint_url}/v1/messages
헤더: Authorization: Bearer <mantle bearer>
      anthropic-version: 2023-06-01
      content-type: application/json
```

- `endpoint_url`은 모델 카탈로그의 값입니다(예: `https://bedrock-mantle.ap-northeast-1.api.aws/anthropic`).
  adapter가 경로 뒷부분만 붙입니다.
- 본문은 **표준 Anthropic Messages**입니다. Bedrock native와 달리 `anthropic_version`은 본문이 아니라
  **헤더**로 가고, `model`은 본문에 들어갑니다. 이 차이를 adapter가 흡수합니다.
- `httpx.AsyncClient` 하나를 공유하고, 스트리밍은 `aiter_lines()`로 SSE `data:` 줄을 읽습니다.
  전 구간 async라 Bedrock adapter 같은 스레드 풀이 필요 없습니다.
- 스트림은 `stream()` 컨텍스트를 열어 **상태 코드를 먼저 읽고**, 200이 아니면 본문을 읽어 로그에
  남긴 뒤 그 상태 코드로 실패를 반환합니다. 컨텍스트는 `finally`에서 반드시 닫습니다.

### bearer broker

```python
class MantleCredentialBroker:
    async def bearer_token(self, region: str) -> str: ...
```

```text
pod 자신의 IRSA 자격 (AssumeRole 없음)
      ↓
bearer = BedrockTokenGenerator().get_token(creds, region)
      → 캐시 키: region.  만료 = min(now + 30분, 자격 만료 − 60초)
```

- **bearer는 리전에 묶입니다.** SigV4가 리전 엔드포인트에 서명하므로 리전이 다르면 다른 토큰이어야
  합니다. 캐시 키가 리전을 빠뜨리면 교차 사용으로 401이 납니다.
- **bearer는 자신을 만든 자격보다 오래 살 수 없습니다.** 자격 만료 60초 전으로 상한을 겁니다.
- 토큰 생성은 동기 SDK 호출이므로 executor에서 실행합니다.
- **토큰과 자격은 로그·예외 메시지·`repr`에 노출되지 않아야 합니다.** dataclass 필드에
  `repr=False`를 명시합니다.

cross-account가 열리면 이 broker에 `assume_role` 경로가 붙고 캐시 키가 `(role_arn, region)`
튜플이 됩니다. 지금 구조가 그 확장을 막지 않도록 캐시 키를 튜플로 시작합니다.

## 사용량 추출

| 경로 | 위치 |
|---|---|
| Bedrock / Mantle (non-stream) | 응답 본문 `usage.input_tokens` / `output_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens` |
| 스트림 | `message_start`의 usage(input) + `message_delta`의 usage(output) 누적 |

`TokenUsage` → `usage_events` 매핑:

| `TokenUsage` | `usage.usage_events` |
|---|---|
| `input_tokens` | `input_tokens` |
| `output_tokens` | `output_tokens` |
| `cache_creation_input_tokens` | `cache_write_tokens` |
| `cache_read_input_tokens` | `cache_read_tokens` |
| `estimated` | `estimated_usage` |

- **provider가 준 값을 우선합니다.** 추정은 provider가 주지 않았을 때의 대비책입니다.
- 추론(reasoning/thinking) 토큰은 이미 `output_tokens`에 포함되어 오는 경우가 있습니다.
  별도로 관측하되 **총합과 비용에 다시 더하지 않습니다.** 이중 과금의 흔한 원인입니다.
- 스트림이 usage 없이 끝나면 누적 텍스트로 출력 토큰을 역산하고 `estimated_usage=true`로 표시합니다.

## 비용 계산

```text
cost = input_tokens      / 1000 × input_price_per_1k
     + output_tokens     / 1000 × output_price_per_1k
     + cache_write_tokens / 1000 × cache_write_price_per_1k
     + cache_read_tokens  / 1000 × cache_read_price_per_1k
```

- 전 구간 `Decimal`입니다. float를 거치지 않습니다.
- `usage_events.estimated_cost_usd`는 `numeric(14,6)`이므로 소수 6자리로 반올림해 넣습니다.
- 계산에 쓴 단가 행의 id를 `pricing_id`에 함께 넣습니다. 단가가 나중에 바뀌어도 어떤 값으로
  계산했는지 되짚을 수 있어야 합니다 ([04](04-backend-routing.md)).
- 단가 행이 없으면 비용 0, `pricing_id` NULL로 기록하고 경고를 남깁니다.

## 타임아웃

| 구간 | 값 | 비고 |
|---|---|---|
| connect | 10s (Bedrock) / 5s (Mantle) | 죽은 엔드포인트를 빨리 포기 |
| non-stream read | 300s | 긴 추론 수용 |
| stream idle | 240s | ALB idle timeout보다 작게 ([01](01-api-entrypoint.md)) |
| 토큰 발급 | 5s | hot path가 아니지만 캐시 miss 시 요청 경로에 들어옴 |

## IAM 권한 (참고)

`infra/terraform`에서 정의할 때의 최소 권한 형태입니다. gateway 코드는 이 권한을 가정만 합니다.

```text
Bedrock native
  bedrock:InvokeModel, bedrock:InvokeModelWithResponseStream
  Resource: foundation-model ARN + inference-profile ARN  ← 둘 다 필요
Mantle
  bedrock-mantle:CreateInference, bedrock-mantle:GetInference   (리전별 ARN)
  bedrock-mantle:CallWithBearerToken
```

cross-region inference profile을 쓰면서 foundation-model ARN을 빼먹는 것이 403의 가장 흔한 원인입니다.

## 테스트 기준

- Bedrock: non-stream 성공, 스트림 성공, 각 AWS 오류 코드의 C6 코드 매핑
- Bedrock: 동기 클라이언트 호출이 이벤트 루프를 막지 않는지 (전용 executor 사용 확인)
- Bedrock: 리전이 다른 두 alias가 각각의 클라이언트를 쓰고, 클라이언트가 캐시되는지
- Mantle: non-200 응답이 200으로 새지 않는지 (스트림·비스트림 각각)
- Mantle: bearer 캐시 키에 리전이 포함되는지, 자격 만료보다 먼저 만료되는지
- 토큰·자격 증명이 로그·예외·`repr` 어디에도 나타나지 않는지
- usage 추출: 스트림/비스트림, cache 토큰 포함, usage 부재 시 추정 플래그
- 비용 계산이 `Decimal`로만 이뤄지고 소수 6자리로 반올림되는지
- 단가 없는 alias → 비용 0 + `pricing_id` NULL + 경고
- adapter가 `NormalizedRequest`·`BackendDecision`만 받고 방언 타입에 의존하지 않는지
  (import 경계 테스트)
- `metadata.user_id`가 `user_id ?? virtual_key_id`로 채워지고, client가 보낸 값이 provider 요청에
  나타나지 않는지
