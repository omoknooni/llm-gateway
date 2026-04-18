# Usage and Cost Observability

## Objective

팀, 사용자, Virtual Key, 모델 단위로 호출량과 토큰 사용량, 추정 비용을 집계해 중앙 비용 관제와 종량제 효과 검증이 가능하도록 합니다.

## What Must Be Captured

- request count
- success / failure count
- input tokens
- output tokens
- total tokens
- latency
- model alias
- underlying provider model id
- team id
- user id
- virtual key id
- request timestamp
- estimated cost

## Aggregation Dimensions

- 시간 단위: hourly, daily, monthly
- 조직 단위: team, user
- 인증 단위: virtual key
- 모델 단위: alias, provider model

## Cost Estimation Baseline

- 기본값은 Bedrock 온디맨드 단가를 기준으로 합니다.
- 입력 토큰과 출력 토큰을 분리해 계산합니다.
- 비용 계산 로직은 모델별 단가 테이블에 의존합니다.
- 내부 정산 단가가 필요해지면 후속 단계에서 별도 레이어로 확장합니다.

## Recommended Event Flow

1. Gateway가 요청 시작 메타데이터를 기록합니다.
2. 응답 또는 실패 시 최종 usage event를 생성합니다.
3. 원천 이벤트는 집계 파이프라인으로 전달됩니다.
4. Postgres에 원천 이벤트와 집계 테이블을 분리 저장합니다.
5. 대시보드는 집계 테이블을 우선 조회합니다.

## Suggested Tables or Concepts

- usage event log
- daily usage aggregate
- monthly usage aggregate
- model pricing reference
- quota / budget snapshot

## Governance Questions This Layer Should Answer

- 어떤 팀이 가장 많은 비용을 사용했는가
- 어떤 사용자가 가장 많은 토큰을 소비했는가
- 어떤 모델이 비용 증가의 주 원인인가
- 특정 Virtual Key가 비정상적으로 많은 호출을 만드는가
- 종량제 전환 시 기존 구독 대비 비용 절감 또는 증가 폭은 어느 정도인가

## Implementation Notes

- 원천 이벤트와 집계 결과를 분리해 보관합니다.
- 비용 계산식은 버전 관리 가능한 참조 데이터로 유지합니다.
- 실패 요청도 운영 관점에서는 중요한 신호이므로 집계 대상에 포함합니다.
- 리더보드와 비용 분석 화면이 동일 집계 원천을 사용하도록 정의를 통일합니다.
