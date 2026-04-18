# Model Evaluation Playground

## Objective

Claude를 포함한 여러 Bedrock 모델을 동일 프롬프트 조건에서 비교 실행해 품질, 응답속도, 비용을 나란히 평가할 수 있는 실험 환경을 제공합니다.

## Why It Exists

- 운영 기본 모델 선택을 데이터 기반으로 결정하기 위해
- 특정 업무 유형에 더 적합한 모델을 찾기 위해
- 품질과 비용의 균형점을 검토하기 위해
- 새로운 Bedrock 모델 도입 전 비교 검증을 수행하기 위해

## Core Capabilities

- 하나의 프롬프트를 여러 모델에 동시 실행
- 모델별 응답 결과 비교
- 응답시간과 토큰 사용량 비교
- Bedrock 단가 기반 추정 비용 비교
- 평가 결과를 운영 정책 수립 자료로 저장

## Separation from Production

- 운영 Gateway와 실험 환경은 논리적으로 분리합니다.
- 실험 호출이 운영 리더보드와 quota 판단에 직접 섞이지 않도록 구분합니다.
- 필요 시 별도의 실험용 key scope 또는 workspace 개념을 둡니다.

## Evaluation Axes

- quality
- latency
- estimated cost
- consistency
- task fit

## Suggested Workflow

1. 비교 대상 프롬프트 또는 테스트 케이스를 등록합니다.
2. 후보 모델 alias를 선택합니다.
3. 동일 입력 조건으로 실행합니다.
4. 결과를 나란히 비교하고 메모 또는 평가를 남깁니다.
5. 필요 시 운영 기본 모델 정책에 반영합니다.

## Implementation Notes

- 실험 결과는 운영 usage aggregate와 분리 저장하는 것이 좋습니다.
- 품질 평가는 정량 지표만으로 충분하지 않으므로 코멘트나 태깅 여지를 둡니다.
- 비교 대상 모델은 운영 허용 모델과 독립적으로 확장 가능해야 합니다.
