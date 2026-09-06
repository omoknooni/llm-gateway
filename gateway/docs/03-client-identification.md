# 03. Client 식별

## Objective

요청을 보낸 **도구(client)** 를 분류해 사용량 귀속과 운영 관측에 씁니다. VK가 "누가"를 답한다면,
client 식별은 "무엇으로"를 답합니다. 같은 사용자가 CLI 도구, 사내 서비스, SDK 스크립트로 각각
호출하면 비용의 성격이 다르고, 어느 도구가 비용을 만드는지 보이지 않으면 조정할 대상을 찾을 수 없습니다.

**범위**: 관측과 귀속에 한정합니다. client를 근거로 백엔드를 바꾸거나 요청을 거절하지 않습니다.
그 이유는 아래 두 절에 있습니다.

## 신뢰 경계

**client는 인가(authorization) 신호가 아닙니다.** User-Agent와 헤더는 client가 마음대로 쓸 수 있는
값입니다. 이 사실이 이 문서 전체의 전제입니다.

| 축 | 신뢰 여부 | 근거 |
|---|---|---|
| VK → 사용자/팀/허용 모델 | 신뢰 | 서버가 발급하고 해시로 검증 |
| client 태그 | **불신** | 요청 헤더에서 옴. 위조 가능 |

따라서 client는 다음 용도로만 씁니다.

1. **사용량 귀속** — `usage.usage_events.client` 컬럼 (신설 요청 S3)
2. **운영 관측** — 구조적 로그와 메트릭 라벨
3. **거절 분석** — `usage.auth_events.client` (신설 요청 S4)

잘못 분류되면 집계 라벨 하나가 `other`가 될 뿐, 어떤 권한도 열리지 않습니다.

## 분류 규칙

우선순위 순으로 판정하고, 첫 일치에서 멈춥니다. 어느 것도 맞지 않으면 `other`입니다.

| 순위 | 신호 | 결과 |
|---|---|---|
| 1 | `x-llmgw-client` 헤더 값이 **등록된 client 집합**에 있음 | 그 값 |
| 2 | `anthropic-client-platform: desktop_app` 또는 UA에 desktop 계열 토큰 | `claude-desktop` |
| 3 | UA가 `claude-cli/`로 시작 | `claude-code` |
| 4 | `originator` 헤더가 `codex`로 시작, 또는 UA에 codex 토큰 | `codex` |
| 5 | UA가 `OpenAI/` · `openai-python` · `openai-node` 계열 | `openai-sdk` |
| 6 | 그 외 | `other` |

- **등록된 client 집합**은 gateway 설정(env / ConfigMap)의 화이트리스트입니다. DB 테이블을 두지
  않습니다 — 이 값은 집계 라벨이지 정책이 아니고, 정책이 아닌 것을 control plane 스키마에 넣으면
  소유권이 흐려집니다. 대신 **값 집합을 아래 표로 계약에 고정**합니다
  ([06](06-contract-response.md) Q3).
- 자유 문자열을 그대로 받아들이지 않는 이유는 카디널리티입니다. `usage_events.client`는 집계 축이고
  메트릭 라벨이므로, 값의 집합이 무제한으로 늘면 집계 테이블과 시계열이 함께 부풀어 오릅니다.
  등록되지 않은 값은 무시하고 다음 순위로 내려갑니다.
- `claude-desktop`을 CLI보다 먼저 보는 이유: 두 도구가 같은 `claude-cli/` UA 접두사를 쓰기 때문입니다.
  순서를 뒤집으면 데스크톱이 CLI로 잘못 분류됩니다.
- 사내 서비스는 UA를 추측당하기보다 `x-llmgw-client`로 **자기 이름을 선언**하게 합니다. 추측 규칙이
  늘어날수록 도구 버전 업그레이드 한 번에 조용히 오분류됩니다.
- 도구 **버전은 client에 넣지 않습니다.** 버전이 필요하면 로그에만 남깁니다.

### 알려진 client 값 (계약)

`usage_events.client` / `auth_events.client`에 들어갈 수 있는 값의 전부입니다. admin 콘솔의 필터
UI는 이 목록을 씁니다 — `usage_events`에서 `DISTINCT`로 뽑지 않습니다. 인덱스 없는 대형 테이블의
전수 스캔이 되기 때문입니다.

| 값 | 대상 |
|---|---|
| `claude-code` | Claude Code CLI |
| `claude-desktop` | Claude 데스크톱 앱 계열 |
| `codex` | OpenAI Codex CLI |
| `openai-sdk` | OpenAI 공식 SDK (python / node) |
| `other` | 분류되지 않음 (예약어. 설정으로 지울 수 없음) |

값 추가·삭제는 **gateway 설정 변경과 이 표의 갱신이 한 쌍**으로 움직입니다. 계약 문서가 바뀌므로
backend에 통보되고, 콘솔은 그때 목록을 맞춥니다. 이는 backend가 `auth_events.outcome`을
"text 컬럼 + 문서로 고정한 값 집합"으로 다루기로 한 것과 같은 방식입니다.

## 구현

```python
# services/client_identifier.py — 순수 함수, I/O 없음
def identify_client(headers: Mapping[str, str], registered: frozenset[str]) -> str: ...
```

```python
# middleware/client_id.py — pure ASGI, Auth 앞에서 실행
state["client"] = identify_client(headers, registered) or CLIENT_OTHER
```

- **절대 예외를 던지지 않습니다.** 어떤 오류가 나도 `other`로 떨어지고 요청은 계속됩니다.
  식별은 관측이지 게이트가 아닙니다.
- Auth **앞**에 두는 이유: 인증 실패 이벤트(`auth_events`)에도 client를 남겨야 "어떤 도구가
  잘못된 키로 오는지"를 볼 수 있기 때문입니다.
- 등록 집합은 설정에서 읽어 프로세스 수명 동안 고정합니다. 값을 바꾸려면 재배포합니다.
  DB 조회도 캐시 만료도 없으므로 이 경로에는 실패할 것이 없습니다.

## 사용량 귀속

`usage.usage_events.client`(S3)로 실립니다. 이를 통해 답할 수 있어야 하는 질문:

- 어떤 도구가 비용의 대부분을 만드는가
- 같은 팀 안에서 CLI 사용과 사내 서비스 사용의 비율은 어떻게 되는가
- 특정 도구가 특정 모델에 몰려 있는가
- 어떤 도구가 인증 실패·모델 거절을 반복하는가 (`auth_events.client`)

S3가 반영되기 전까지는 구조적 로그와 메트릭에만 남고 DB 집계에서는 빠집니다. 기능은 그대로
동작하되 분해가 안 될 뿐이므로, S3를 M5의 선행 조건으로 두지 않습니다.

## 이번 범위에서 제외한 것

### VK별 `allowed_clients` 게이팅

특정 VK를 특정 도구에서만 쓸 수 있게 제한하는 기능입니다. **넣지 않습니다.**

- 근거 데이터가 없습니다. backend 스키마에 `allowed_clients` 컬럼도 테이블도 없고,
  C2의 `vk:auth` payload에도 없습니다.
- 넣더라도 **위장을 막지 못합니다.** 허용 목록에 없는 도구로 넘어가는 것은 막지만, 허용된 도구 중
  하나로 자신을 위장하는 것은 막지 못합니다. 헤더가 근거이기 때문입니다.
- 진짜 통제가 필요한 축(모델 접근, 예산, rate limit)은 전부 VK에 걸려 있고, 그쪽은 위조할 수 없습니다.

"도구 A에서는 이 모델만"이라는 요구가 실제로 생기면, 도구별로 **VK를 따로 발급**하는 것이 더
정확한 해법입니다. VK는 이미 허용 모델을 축소할 수 있고 위조되지 않습니다. 그때는 이 문서가 아니라
[02](02-virtual-key-auth.md)의 VK 층 축소로 해결됩니다.

### client별 routing profile

[04](04-backend-routing.md)에서 다룹니다. 요약하면, 리전과 엔드포인트는 `model_aliases`가 이미
소유하고 있어 client 축을 하나 더 만들 근거가 없습니다.

## 테스트 기준

- 각 분류 규칙별 대표 UA/헤더 조합 → 기대 client (테이블 주도 테스트)
- 데스크톱 계열이 CLI보다 먼저 판정되는지 (순서 회귀 방지)
- 등록되지 않은 `x-llmgw-client` 값 → 무시하고 UA 추론으로 내려감
- 헤더 디코딩 실패 등 비정상 입력 → 예외 없이 `other`
- 인증 실패 요청의 `auth_events`에도 client가 실리는지 (미들웨어 순서 회귀 방지)
- 분류 결과가 위 "알려진 client 값" 표를 벗어나지 않는지 (설정에 미등록 값을 넣어도)
