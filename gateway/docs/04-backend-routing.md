# 04. 백엔드 라우팅

## Objective

인증된 요청 하나를 **어떤 모델을, 어떤 provider로, 어느 리전에서** 호출할지 결정합니다.
이 단계의 산출물은 `BackendDecision` 하나이며, provider adapter는 이것만 받아 호출합니다.

**결정의 원천은 모델 카탈로그 하나입니다.** `model.model_aliases` 행 하나가 provider,
provider_model_id, 리전, 엔드포인트, 지원 방언, 단가를 전부 갖고 있습니다. 라우팅은 그 행을
찾아 읽는 일이지, 여러 축을 합성하는 일이 아닙니다.

## client별 routing profile을 두지 않는 이유

초기 계획에는 `routing_profiles`(client → backend·region·account·default_model) 테이블이
있었습니다. 참조 구현(`awsome-ai-gateway`)에 있고, client마다 다른 계정·리전으로 나가야 하는
그쪽 요구에서 온 구조입니다. **채택하지 않습니다.**

- Phase 1에서 확정된 backend 스키마에 이 테이블이 없고, `client` 개념 자체가 없습니다.
- `model_aliases.region`이 이미 **모델별 리전**을 갖고 있습니다. "어디서 부를까"의 답을
  카탈로그가 이미 알고 있는데 client 축을 하나 더 만들면 두 곳이 같은 질문에 답하게 됩니다.
- client별로 백엔드나 계정을 갈라야 하는 요구가 현재 요구사항에 없습니다. 참조 구현의 그 구조는
  제품 특화 사정(도구마다 다른 AWS 계정)에서 왔고, 우리에겐 그 사정이 없습니다.
- 요청한 모델을 무시하고 다른 모델로 바꿔치는 `force_default_model`은 client 입장에서 A를
  요청했는데 B가 응답하는 동작입니다. 이를 지탱할 근거가 없는 상태로 먼저 만들지 않습니다.

필요해지면 그때 ADR로 다시 꺼냅니다. `BackendDecision`을 만드는 로직은 라우터 본문이 아니라
별도 함수로 분리해, 축이 하나 늘어도 라우터를 건드리지 않게 둡니다.

## 모델 해석

```text
model_alias (client가 보낸 문자열)
   │
   ├─ GET policy:model:{ref} ── hit ──▶ ModelConfig
   │
   ▼ miss
 PostgreSQL: model.model_aliases WHERE alias = :ref
             없으면        WHERE provider_model_id = :ref   (LIMIT 1)
   │
   ├─ 없음          ──▶ 404 model_inactive
   ├─ status≠ACTIVE ──▶ 404 model_inactive (로그에는 inactive 로 구분)
   │
   ▼
 최신 유효 단가 1건 (effective_from ≤ now < effective_until, 없으면 NULL)
   │
   ▼
 ModelConfig ──▶ SETEX policy:model:{alias}, policy:model:{provider_model_id} 300s
```

```python
@dataclass(frozen=True)
class ModelConfig:
    alias: str
    provider: Provider                  # BEDROCK | BEDROCK_MANTLE(S1 반영 후)
    provider_model_id: str
    region: str | None                  # None = 배포 기본 리전
    endpoint_url: str | None            # Mantle 계열만 사용 (S2 반영 후)
    supported_dialects: list[str]       # OPENAI_CHAT | ANTHROPIC_MESSAGES
    status: ModelStatus
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_streaming: bool
    pricing: ModelPricing | None        # 단가 4종
    pricing_id: str | None              # usage_events.pricing_id 로 그대로 실림
```

- **`pricing_id`를 반드시 함께 캐시합니다.** `usage.usage_events.pricing_id`가 "어떤 단가로
  계산했는지"를 추적하는 컬럼이라, 비용을 계산한 그 행의 id가 필요합니다. 단가만 들고 오면
  나중에 단가가 바뀌었을 때 어느 값으로 계산했는지 되짚을 수 없습니다.
- **alias와 provider_model_id를 둘 다 수용**합니다. client가 `apac.anthropic.claude-...`를 그대로
  보내는 경우가 실제로 있습니다. 해석 후에는 두 키 모두 캐시에 채워 다음 요청이 한 번에 끝나게 합니다.
- **단가 행이 없는 alias도 호출은 됩니다.** 비용이 `0`으로 기록되고 `pricing_id`가 NULL이 될 뿐입니다.
  단가 누락은 backend의 감지 job이 다룰 운영 문제이지, 요청을 죽일 이유가 아닙니다.
  대신 이 경우 경고 로그와 메트릭을 남겨 조용히 0원으로 집계되지 않게 합니다.
- `status = INACTIVE`는 **운영자의 kill switch**입니다. 다른 모델로 조용히 우회시키지 않고 거절합니다.
  우회시키면 끈 모델의 트래픽이 다른 모델의 비용으로 나타나 원인 추적이 불가능해집니다.
- 캐시 항목 파싱 실패는 예외가 아니라 **miss로 취급**해 DB에서 재구성합니다(자가 치유).

## 방언 호환성 검사

모델마다 노출 방언이 다릅니다. `model_aliases.supported_dialects`가 그 근거이며, 빈 배열은
DB 제약으로 막혀 있습니다.

```text
요청 방언 ∉ ModelConfig.supported_dialects  →  400 dialect_not_supported
    "Model 'llama-3' is not available on the Anthropic Messages endpoint"
```

메시지에 대안 엔드포인트를 적어 client가 스스로 고칠 수 있게 합니다.
스트리밍 요청인데 `supports_streaming=false`이면 같은 방식으로 400입니다.

## 접근 범위 검사 (ScopeCheck)

`AuthContext.allowed_model_aliases`는 [02](02-virtual-key-auth.md)에서 3층 해석이 끝난
**최종 목록**입니다. 여기서는 멤버십만 봅니다.

```text
ModelConfig.alias ∉ allowed_model_aliases  →  403 model_not_allowed
```

- **비교는 `alias` 하나로만 합니다.** 허용 목록에는 alias만 들어 있고, 해석된 `ModelConfig`를
  기준으로 보므로 client가 provider_model_id로 요청해도 같은 판정이 나옵니다. 요청 문자열로
  비교하면 같은 모델을 다른 이름으로 불러 화이트리스트를 우회할 수 있습니다.
- 검사는 **모델 해석 이후, 호출 이전**입니다. 해석보다 앞서면 존재하지 않는 모델에 403을 주게 됩니다.
- **ScopeCheck를 방언 호환성 검사보다 먼저** 합니다. 허용되지 않은 키는 어떻게 물어보든 같은
  답(403)을 받아야 합니다. 방언 검사가 앞서면 권한 없는 키가 그 모델의 지원 방언을 알아냅니다.
- 3층 해석에서 이미 INACTIVE가 제외되므로, 허용 목록에 있다는 것은 카탈로그에서 살아 있다는
  뜻이기도 합니다. 그래도 `ModelConfig.status`를 다시 봅니다 — 캐시 만료 시점이 서로 다릅니다.

## BackendDecision

```python
@dataclass(frozen=True)
class BackendDecision:
    model: ModelConfig
    provider: Provider
    call_model_id: str          # 리전 접두사 재작성이 끝난 최종 모델 ID
    region: str                 # model.region ?? 배포 기본 리전
    endpoint_url: str | None    # Mantle 계열
```

결정 순서:

```text
1. model   ← alias 해석 (Redis → DB)
2. ScopeCheck → 방언 호환성 검사
3. provider ← model.provider          카탈로그가 결정한다
4. region   ← model.region ?? settings.aws_region
5. call_model_id ← 리전 접두사 재작성
```

**3번이 핵심입니다.** 어떤 provider를 쓸지는 모델 카탈로그가 결정합니다. 다른 축이 provider를
바꾸면 같은 alias가 상황에 따라 다른 백엔드로 가서, 단가 테이블과 실제 호출이 어긋납니다.

## 리전 접두사 재작성

Bedrock의 cross-region inference profile ID는 리전군 접두사를 가집니다.

```text
us.anthropic.claude-sonnet-4-5-...    (미국)
eu.anthropic....                      (유럽)
apac.anthropic....                    (아시아·태평양)
global.anthropic....                  (어디서든 해석됨 — 그대로 통과)
```

호출 리전과 접두사가 다르면 `ValidationException`이 납니다. 대상 리전에 맞는 접두사로 바꿉니다.

```text
provider_model_id = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
region            = "ap-northeast-2"          # model_aliases.region
call_model_id     = "apac.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

- 알려진 접두사(`us` / `eu` / `apac` / `global`)가 아니면 손대지 않습니다.
- `global.`은 통과시킵니다.
- 재작성이 일어나면 로그에 원본과 결과를 남깁니다. 카탈로그에 잘못된 리전으로 등록된 alias를
  찾는 단서가 되고, **재작성이 상시 발생한다면 그건 카탈로그를 고쳐야 한다는 신호**입니다.
  재작성은 안전망이지 정상 경로가 아닙니다.

## `/v1/models` 목록

OpenAI 호환 목록 엔드포인트는 **VK가 실제로 부를 수 있는 모델만** 반환합니다.

```text
AuthContext.allowed_model_aliases  ∩  policy:model:list (카탈로그 ACTIVE)
```

허용 목록이 이미 3층 해석과 INACTIVE 제외를 거친 결과이므로, 교집합은 방어적 재확인입니다.
목록과 집행이 서로 다른 판단을 쓰면 client는 보이는 모델을 부르고 403을 받습니다.

응답은 **OpenAI 표준 형태**(`id` / `object` / `created` / `owned_by`)만 담습니다. 초안에서는
각 항목에 `supported_dialects`를 실으려 했지만 철회했습니다 — OpenAI SDK는 비표준 필드를
노출하지 않아 client가 읽을 수 없고, 실으려면 목록의 모든 alias를 개별 해석해야 합니다.
방언이 맞지 않는 모델은 호출 시점에 `dialect_not_supported`가 대안 엔드포인트를 알려줍니다.

## 실패 정책

| 상황 | 내부 코드 | HTTP |
|---|---|---|
| Redis 장애 | — | DB 직접 조회로 계속 |
| DB 장애 | — | 캐시 hit만 통과, miss는 503 |
| 둘 다 장애 | — | 503 |
| 모델 미등록 / INACTIVE | `model_inactive` | 404 |
| 방언 불일치 / 스트리밍 미지원 | `dialect_not_supported` | 400 |
| 범위 밖 모델 | `model_not_allowed` | 403 |

모델 해석은 fail-closed입니다. 확인하지 못한 모델을 통과시키지 않습니다.
403·404 거절은 provider 호출이 없었으므로 `usage_events`가 아니라 `usage.auth_events`로 갑니다.

## 이번 범위에서 제외

`BackendDecision`을 만드는 자리가 나중에 이들을 받을 수 있도록 결정 로직을 분리해 두되,
지금은 구현하지 않습니다.

- **가용성 fallback 체인** — 5xx 시 같은 provider의 대체 alias로 재시도
- **circuit breaker** — 모델별 실패율 기반 차단
- **예산 기반 모델 강등(downgrade)** — 예산 집행이 붙은 뒤에도 도입하지 않습니다. 사용자가
  모르는 사이 응답 품질이 바뀝니다 ([08](08-enforcement.md))
- **cross-account 호출** — role ARN을 둘 자리가 스키마에 없습니다. 필요해지면 그 자리를 만드는
  것부터 ADR로 다룹니다.

## 테스트 기준

- alias / provider_model_id 양쪽으로 같은 `ModelConfig`가 나오는지
- `pricing_id`가 캐시를 왕복해도 보존되는지 (usage 기록의 선행 조건)
- 단가 행이 없는 alias → 호출은 성공, 비용 0, `pricing_id` NULL, 경고 발생
- INACTIVE alias가 우회 없이 404가 되는지
- 화이트리스트 우회 시도(provider_model_id로 요청) 차단
- 방언 불일치가 400과 대안 안내 메시지를 주는지
- `supports_streaming=false` 모델에 `stream=true` → 400
- 리전 접두사 재작성: us→apac, global 통과, 미지 접두사 무변경, `region` NULL 시 배포 기본값
- `/v1/models`가 허용 범위 밖 모델을 노출하지 않는지
- Redis/DB 장애 조합별 동작
