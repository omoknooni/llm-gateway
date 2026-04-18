# Gateway Architecture

## Objective

LiteLLM을 사내 공통 LLM Gateway로 사용해, 다양한 AWS Bedrock 모델을 동일한 호출 인터페이스로 표준화합니다. 외부 클라이언트는 OpenAI 호환 경험을 유지하고, 내부에서는 모델 카탈로그와 정책 계층을 통해 실제 Bedrock 모델로 라우팅합니다.

## Responsibilities

- OpenAI 호환 요청 인터페이스 제공
- 내부 표준 모델명과 Bedrock 실제 모델 ID 매핑
- 팀/사용자/Virtual Key 기반 모델 접근 허용 여부 검증
- 호출 이벤트, 응답 메타데이터, 오류, 지연시간 기록
- 운영 Gateway와 실험 Gateway의 논리적 분리 지원

## Core Design

- 외부 요청은 Virtual Key로 인증합니다.
- Gateway는 요청받은 표준 모델명을 내부 모델 카탈로그에서 조회합니다.
- 카탈로그는 실제 Bedrock 모델 ID, 활성 상태, 기본 파라미터, 정책 태그를 가집니다.
- LiteLLM은 카탈로그 정보에 따라 Bedrock 호출을 수행합니다.
- 호출 결과는 사용량 이벤트로 변환되어 집계 파이프라인으로 전달됩니다.

## Suggested Interfaces

- Public model name
  - 예: `claude-sonnet`, `claude-haiku`, `titan-text`, `nova-pro`
- Internal model catalog fields
  - `model_alias`
  - `provider`
  - `bedrock_model_id`
  - `default_params`
  - `quality_tier`
  - `latency_tier`
  - `cost_tier`
  - `is_active`

## Routing Rules

- 클라이언트는 가능한 한 표준 alias만 사용합니다.
- 운영자는 alias와 실제 Bedrock 모델 매핑을 교체할 수 있어야 합니다.
- 팀 또는 키 단위로 허용 모델 whitelist를 둘 수 있어야 합니다.
- 실험 환경에서는 동일 alias를 여러 후보 모델과 비교 실행할 수 있어야 합니다.

## Non-Functional Requirements

- 모델 추가 시 클라이언트 인터페이스 변경을 최소화합니다.
- 요청/응답 경로에 audit 가능한 메타데이터를 남깁니다.
- 실패 시 provider 오류와 policy 오류를 구분해 기록합니다.
- 추후 multi-provider 확장이 가능하도록 provider 추상화를 유지합니다.

## Implementation Notes

- LiteLLM 설정과 별개로 사내 운영용 모델 카탈로그를 유지합니다.
- FastAPI control plane이 카탈로그와 정책 정보를 관리합니다.
- Gateway 인스턴스는 정책 조회를 위해 control plane 또는 캐시 계층과 연동합니다.
