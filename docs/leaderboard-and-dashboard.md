# Leaderboard and Dashboard

## Objective

운영자가 팀, 사용자, 모델, Virtual Key 기준의 사용량과 추정 비용을 빠르게 파악하고, 상위 사용 주체와 패턴을 한눈에 볼 수 있는 내부 관제 UI를 제공합니다.

## Primary Views

- 팀별 리더보드
- 사용자별 리더보드
- 모델별 사용량 및 비용 분포
- Virtual Key 사용 이력 및 상태 화면
- 기간별 비용 추이
- 오류율 및 지연시간 요약

## Minimum Dashboard Metrics

- total requests
- total input tokens
- total output tokens
- total estimated cost
- top teams
- top users
- top models
- failed request rate
- average latency

## Leaderboard Requirements

- 호출량 기준 정렬
- 토큰 사용량 기준 정렬
- 추정 비용 기준 정렬
- 기간 필터: day, week, month
- 팀/사용자/모델 drill-down

## Visualization Guidance

- 상위 사용 팀/사용자를 즉시 파악할 수 있어야 합니다.
- 비용 집중 모델과 사용량 집중 모델을 분리해 볼 수 있어야 합니다.
- 리더보드는 단순 순위표를 넘어서 사용 패턴을 설명해야 합니다.
- 운영자는 키 상태 변화와 이상 사용 흔적을 함께 확인할 수 있어야 합니다.

## Suggested UI Modules

- overview cards
- leaderboard tables
- trend charts
- model mix chart
- key audit timeline
- filter bar

## Implementation Notes

- 대시보드는 집계 테이블을 우선 사용해 응답성을 확보합니다.
- 운영자 관점에서 액션 가능한 정보가 먼저 보여야 합니다.
- 비용, 토큰, 호출 수는 동일 기간 조건에서 일관되게 계산되어야 합니다.
