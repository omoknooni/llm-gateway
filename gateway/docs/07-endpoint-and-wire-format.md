# 07. Bedrock 엔드포인트 지형과 wire format 축

## Objective

Amazon Bedrock이 OpenAI 호환 API를 `bedrock-runtime`에도 노출하기 시작한 사실을 확인하고,
그것이 [05](05-provider-invocation.md)에서 고정한 provider 설계에 무엇을 요구하는지 판단합니다.

**결론부터**: 지금 코드에 변경할 것이 없습니다. 대신 [05](05-provider-invocation.md)의 인증
서술에 사실 오류가 있어 정정하고, GPT 계열을 실제로 서비스하려면 무엇이 필요한지를 M7 후보로
남깁니다. 그 "무엇"은 엔드포인트가 아니라 **wire format**입니다.

조사 시점은 **2026-09-12**이고 근거는 아래 공식 문서입니다. 모델별 가용성은 자주 바뀌므로
이 문서의 모델 목록은 스냅샷으로 읽고, 실제 등록 시점에 원문을 다시 봅니다.

- [Endpoints supported by Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html)
- [Endpoint availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-endpoint-availability.html)
- [Responses API / bedrock-mantle](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-mantle.html)
- [Cross Region Inferencing for OpenAI models (2026-08)](https://aws.amazon.com/about-aws/whats-new/2026/08/amazon-bedrock-cross-region-openai-v2/)

## 두 엔드포인트

| | `bedrock-runtime.{region}.amazonaws.com` | `bedrock-mantle.{region}.api.aws` |
|---|---|---|
| 지원 API | InvokeModel / Converse / Chat Completions / Responses / Messages | Chat Completions / Responses / Messages |
| OpenAI 호환 경로 | `/openai/v1/...` | `/v1/...` |
| 인증 | **SigV4 + Bedrock API key 둘 다** | **SigV4 + Bedrock API key 둘 다** |
| IAM 액션 | `bedrock:InvokeModel` / `…WithResponseStream` | `bedrock-mantle:CreateInference` |
| cross-Region inference | 지원 | **미지원** |
| Guardrails / intelligent prompt routing | 지원 | 미지원 |
| 서버사이드 tool·web search, 비동기 추론, Projects·Workspaces | 미지원 | 지원 |
| 쿼터 체계 | 모델별 고정 RPM/TPM | 큐잉 기반 fair-share, 초기 한도가 더 높음 |

AWS의 입장은 *"For most new applications, use the `bedrock-runtime` endpoint"* 이지만, 같은 문서가
*"Existing applications that use `bedrock-mantle` continue to be fully supported and **do not need to
change**"* 라고 명시합니다. **폐기 예고가 아닙니다.**

두 엔드포인트는 같은 추론 엔진 위에 있습니다 — *"The `bedrock-mantle` name identifies an **endpoint
surface, not a different inference engine**."* 동일 모델의 토큰 단가도 같습니다. 그래서 엔드포인트
선택의 기준은 비용이 아니라 **필요한 API와 기능**입니다.

## 엔드포인트 가용성은 모델별 속성이다

이것이 이 조사의 핵심 발견입니다. 전역 스위치가 아니라 카탈로그 행마다 다릅니다.

| | 모델 (2026-09-12 스냅샷) |
|---|---|
| **mantle 전용** | GPT-5.5, GPT-5.4, Daybreak Red(GPT-5.6 Cyber), Daybreak Blue(GPT-5.6 Sol), Claude Mythos 5, Claude Mythos Preview, Gemma 4 계열, Grok 4.3 |
| **runtime 전용** | Claude Sonnet 4·4.5·4.6, Claude Opus 4.1·4.5·4.6, Claude Mythos 5.1, Claude 3/3.5 Haiku, Nova·Llama·Titan 계열 |
| **양쪽** | GPT-6 Astra, GPT-5.6 Sol·Terra·Luna, gpt-oss-120b·20b, Claude Opus 5, Claude Sonnet 5, Claude Fable 5·5.1, Claude Haiku 4.5, Claude Opus 4.7·4.8 |

양쪽 모두 실제 트래픽을 받을 대상이고, 한쪽으로 수렴시킬 수 없습니다. 어느 한쪽만 지원하기로
하면 카탈로그에 올릴 수 없는 모델이 생깁니다.

## 우리 구조에서 바꾸지 않는 것

### 1. S1·S2를 되돌리지 않습니다

`model.provider` 의 `BEDROCK_MANTLE` 값(S1)과 `model_aliases.endpoint_url` 컬럼(S2)은
[06](06-contract-response.md)에서 요청해 backend 마이그레이션 `0004`·`0005`로 반영된 항목입니다.
mantle 전용 모델이 계속 존재하고 AWS가 명시적으로 지속 지원을 약속한 이상, 이 둘을 되돌리는
계약 왕복은 순손실입니다.

### 2. 엔드포인트 이동은 코드 변경이 아니라 카탈로그 데이터 변경입니다

[04](04-backend-routing.md)가 고정한 **"결정의 원천은 모델 카탈로그 하나"** 원칙이 여기서
배당금을 냅니다. 어떤 모델을 mantle에서 runtime으로 옮기려면 그 alias 행의 `provider`와
`endpoint_url`만 갈면 되고, gateway 코드도 재배포도 필요 없습니다. 캐시 무효화까지 backend의
기존 경로를 그대로 탑니다.

라우팅이 여러 축을 합성하는 구조였다면 여기서 분기가 생겼을 것입니다. 한 행을 읽는 구조라
엔드포인트는 그 행의 값 하나입니다.

### 3. 리전 접두사 재작성은 이미 provider 중립입니다

`services/region.py` 는 `us` / `eu` / `apac` / `global` 접두사를 **문자열 수준에서** 다루므로
`us.openai.gpt-5.6-sol` 도 그대로 처리합니다. GPT 계열은 runtime에서 in-Region 추론이 불가하고
cross-Region inference profile을 반드시 지명해야 하는데, 그 형태가 이미 우리가 다루는 형태입니다.

GovCloud의 `us-gov.` 접두사는 `KNOWN_PREFIXES` 에 없지만, 모르는 접두사는 **손대지 않는 쪽으로
실패**하도록 짜여 있어 안전합니다. GovCloud를 쓰지 않는 한 손댈 이유가 없습니다.

### 4. AWS 측 사용량 귀속 기능은 여전히 쓰지 않습니다

runtime은 IAM principal·request metadata tagging·application inference profile로, mantle은
Projects·Workspaces로 사용량을 귀속시킬 수 있습니다. 둘 다 쓰지 않습니다 — 우리의 귀속 단위는
VK·팀·사용자이고 그 원천은 `usage.usage_events` 입니다. AWS 측 귀속을 섞으면 두 개의 집계가
생기고 어느 쪽이 정답인지 다투게 됩니다.

## 정정 — 인증은 엔드포인트의 속성이 아니다

[05](05-provider-invocation.md)의 비교표가 전송 방식과 인증을 **provider의 정체성처럼** 적어
뒀는데, 이 부분이 공식 문서와 어긋납니다.

| 항목 | 기존 서술 | 사실 |
|---|---|---|
| 인증 | Bedrock = SigV4, Mantle = Bearer | **두 엔드포인트 모두 SigV4와 Bedrock API key를 지원** |
| IAM 네임스페이스 | `bedrock:` vs `bedrock-mantle:` | 그대로 사실 |

`MantleCredentialBroker` 가 bearer를 쓰는 것이 잘못됐다는 뜻이 아닙니다. 문제는 문서가 **우리의
선택을 필연으로 적어 둔 것**입니다. 그대로 두면 나중에 "runtime이니까 boto3여야 한다" 같은
잘못된 추론의 근거가 됩니다. 실제로는 runtime의 `/openai/v1` 경로를 bearer로 부를 수도 있고,
mantle을 SigV4로 부를 수도 있습니다.

## 진짜 제약 — provider 축이 전송만 구분한다

**지금 gateway는 GPT 계열을 어느 엔드포인트로도 호출하지 못합니다.** 이 뉴스와 무관하게 그렇고,
뉴스가 없었어도 그랬습니다.

```text
providers/bedrock.py  build_body()   → Anthropic Messages wire (anthropic_version, system, thinking)
                      parse_response() → Anthropic content 블록
providers/mantle.py   ──────────────── 위 두 함수를 그대로 import 해서 재사용
```

즉 provider 축은 **전송(boto3 vs httpx)만 구분하고 wire format은 Anthropic 하나로 고정**돼
있습니다. 실제로 필요한 축은 둘입니다.

| 축 | 값 |
|---|---|
| 엔드포인트 / 전송 | `bedrock-runtime` (boto3 InvokeModel, 또는 httpx + `/openai/v1`) · `bedrock-mantle` (httpx) |
| wire format | Anthropic Messages · OpenAI Chat Completions · (Converse) |

GPT 도입에 필요한 것은 "bedrock-runtime으로 옮기기"가 아니라 **OpenAI Chat Completions wire를
말하는 adapter를 추가하는 것**입니다. 두 축은 직교합니다.

## M7 후보 — OpenAI Chat Completions adapter

착수 여부는 "GPT 계열을 사내에 열 것인가"라는 **제품 결정**에 달려 있습니다. 결정되면 아래 형태로
갑니다. Phase 4보다 뒤입니다.

### 형태

```text
POST {endpoint_url}/chat/completions
  endpoint_url = https://bedrock-runtime.{region}.amazonaws.com/openai/v1
              or https://bedrock-mantle.{region}.api.aws/v1
```

- `MantleAdapter` 의 HTTP 골격(async httpx, 상태 코드 선확정, SSE `aiter_lines`, 스트림 컨텍스트
  `finally` 종료)을 재사용하고 **body 직렬화와 응답 파싱만 교체**합니다.
- **`endpoint_url`(S2)이 여기서 다시 쓰입니다.** 추가 스키마 변경이 필요 없습니다.
- `Converse` API로 통일하는 대안은 권하지 않습니다. Converse wire를 새로 구현해야 하고, 이미 도는
  Anthropic-native 경로까지 갈아엎는 비용이 Guardrails 지원이라는 이득보다 큽니다.
  [05](05-provider-invocation.md)의 "모델군이 늘면 그때 Converse adapter를 **추가**한다"는 판단은
  유효하고, 지금이 그 시점은 아닙니다.

### 착수 시 반드시 짚을 것

1. **스트리밍 usage 누락** — OpenAI Chat Completions SSE는 `stream_options.include_usage` 를
   켜지 않으면 usage 청크를 주지 않습니다. gateway는 **provider 방향으로 항상 켜야** 합니다.
   빠뜨리면 스트리밍 GPT 호출의 비용이 조용히 0으로 집계됩니다 — [README](README.md)가 "비용
   관제에서 가장 나쁜 실패 형태"로 지목한 그 형태입니다.
2. **`TokenUsage` 4종 매핑** — OpenAI wire에는 `cache_write` 에 대응하는 값이 없습니다.
   `prompt_tokens_details.cached_tokens` 가 `cache_read` 에 대응하고, `cache_write` 를 0으로 둘지
   `estimated_usage=true` 로 표시할지 정해야 합니다. 비용 계산식이 4종 전부를 곱하므로 이
   결정이 단가에 직접 닿습니다.
3. **경계 침범 주의** — `dialects/openai.py`(client→gateway)를 provider 방향에 재사용하고 싶은
   유혹이 생기는데, 그러면 [README](README.md)의 **"1~4단계는 provider를 모르고 5단계는 방언을
   모른다"** 가 깨집니다. client가 보낸 OpenAI 본문을 그대로 upstream에 흘리는 지름길은 정규화
   계층을 우회하는 것이고, 그 순간 정책 집행과 usage 계측이 통과하지 않는 경로가 생깁니다.
   **별도 모듈이어야 합니다.**
4. **오류 매핑** — 엔드포인트마다 쿼터 체계가 달라(고정 RPM/TPM vs 큐잉) 같은 모델이라도 429의
   의미와 빈도가 다릅니다. [05](05-provider-invocation.md)의 매핑표에 OpenAI wire의 오류 형태를
   추가하되, upstream 429와 우리 rate limit의 429를 구분하는 원칙은 그대로 지킵니다.

### ADR 후보 — provider enum의 축

`BEDROCK` / `BEDROCK_MANTLE` 은 **엔드포인트**를 뜻하는 값인데, 여기에 wire format 축이 들어오면
두 축이 한 컬럼에 섞입니다. 선택지는 두 갈래입니다.

- (a) provider 값을 늘린다 — 조합 수만큼 값이 생겨 곱셈이 시작됩니다.
- (b) 엔드포인트는 이미 `endpoint_url` 이 표현하므로, `provider` 를 **wire format**의 의미로
  재해석한다 — 기존 두 값의 뜻이 바뀌므로 backend와의 계약 변경입니다.

**backend 계약 변경이므로 단독으로 정하지 않습니다.** [worktree-integration.md](../../docs/worktree-integration.md)의
계약 변경 절차대로, GPT 지원을 실제로 착수하기로 한 시점에 backend 브랜치와 왕복하고 `main`에서
ADR 번호를 받습니다. 그전까지는 후보로만 둡니다.

## 이번 범위에서 제외

- Responses API 지원 — 우리는 Chat Completions와 Anthropic Messages 두 방언만 노출합니다
  ([ADR-0003](../../docs/adr-0003-client-api-dialects.md)). Responses는 상태 저장(`store`,
  `previous_response_id`)이 기본값 `true` 라 대화 내용이 AWS 측에 30일 보존됩니다. 방언으로
  받으려면 데이터 보존 정책부터 정해야 하므로 별건입니다.
- Guardrails, intelligent prompt routing — runtime 전용 기능이지만 정책 집행은 gateway가
  소유합니다. 두 곳에서 거절이 일어나면 원인 추적이 어려워집니다.
- 서버사이드 tool use, web search — [README](README.md) Non-Goals 그대로 유지합니다.
