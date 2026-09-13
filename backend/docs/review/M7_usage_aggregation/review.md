# M7 사용량 집계·조회 구현 리뷰

| 항목 | 내용 |
|---|---|
| 대상 커밋 | `f3cca16` — `FEAT : 사용량 집계와 대시보드·리더보드 조회 (M7)` |
| 검토일 | 2026-09-12 |
| 결론 | 아래 P1 항목을 수정하기 전 병합 보류 |

## P1 — 초기 배포 이전 이벤트와 lookback 밖의 지연 이벤트가 영구히 집계되지 않음

일·월 집계 job은 `USAGE_AGGREGATION_LOOKBACK_DAYS`(기본 3)만큼의 최근 일자만 원천에서 읽고
UPSERT한다. M7 이전에도 gateway는 `usage.usage_events`를 직접 기록하도록 구현되어 있으므로,
M7을 배포할 때 이미 3일보다 오래된 원천 이벤트는 일·월 집계 테이블에 한 번도 쓰이지 않는다.
이후 job도 같은 최근 구간만 다시 계산하므로 해당 이벤트는 영구히 대시보드·리더보드·예산
breakdown에서 빠진다.

같은 이유로 DB 장애나 gateway 스풀 재시도로 발생 시점보다 3일 늦게 도착한 이벤트도 놓친다.
gateway의 스풀은 메모리 기반이며, 장애가 lookback보다 길지 않다는 계약이나 백엔드에 전달되는
지연 상한이 없다.

관련 코드:

- `aggregate_usage_daily()`와 `aggregate_usage_monthly()`가 동일한 최근 구간만 집계한다.
- 기본 lookback은 3일이다.
- gateway는 사용량 레코드를 메모리 스풀에 보관했다가 DB 복구 후 기록한다.

권장 수정:

1. M7 배포 시 전체 과거 원천을 집계하는 일회성 backfill 명령 또는 job을 제공한다.
2. 정상 주기 집계에서는 lookback을 유지하되, gateway가 보장하는 최대 지연보다 충분히 길게
   설정하거나 지연 이벤트를 재집계 대상으로 식별할 수 있는 별도 복구 절차를 둔다.
3. lookback보다 오래된 원천 이벤트가 처음으로 도착했을 때 일·월 집계와 조회 결과에 반영되는
   통합 테스트를 추가한다.

## P1 — 월 단위 trend가 부분 월 요청에 그 달 전체 집계를 반환함

`GET /usage/trend?granularity=MONTH`는 월 집계 테이블을 `period >= from_date의 월` 및
`period <= to_date의 월` 조건으로만 조회한다. 따라서 `from_date=2026-09-15`와
`to_date=2026-09-20`을 요청해도 `2026-09` 행 전체, 즉 9월 1일부터 30일까지의 비용·호출 수·
토큰을 반환한다.

문서는 `from_date`와 `to_date`가 모든 조회의 UTC 일자 범위이며 양끝을 포함한다고 정의한다.
부분 월 요청에서 범위 밖 사용량이 포함되면 overview·leaderboard와 trend의 숫자가 달라지고,
사용자가 설정한 기간 필터를 신뢰할 수 없다.

관련 코드:

- 월 trend는 기간의 월 문자열만 비교한다.
- 일 trend는 정확한 일자 범위를 사용하므로 두 granularity의 의미가 다르다.

권장 수정:

1. 월 trend도 일 집계 테이블에서 정확한 일자 범위를 필터한 뒤 월별로 묶는다. 응답에 p95를
   싣지 않으므로 일 집계의 합계·가중 평균으로 정확하게 계산할 수 있다.
2. 월 집계 테이블을 계속 사용해야 한다면, 양 끝의 부분 월은 일 집계로 계산하고 그 사이의
   완전한 월만 월 집계를 사용하는 방식으로 합친다.
3. 부분 월, 여러 월, 연도 경계의 trend가 overview와 같은 합계를 반환하는 통합 테스트를
   추가한다.

## P2 — overview의 여러 SELECT가 같은 집계 시점을 보장하지 못함

overview는 합계와 세 개의 top 목록을 순차로 조회한다. 코드 주석은 한 응답으로 묶어 집계 job
사이의 수치 불일치를 방지한다고 설명하지만, 명시적 repeatable-read 읽기 트랜잭션이 없다.
PostgreSQL 기본 `READ COMMITTED`에서는 각 SELECT가 새 스냅샷을 보므로 집계 job의 커밋이
쿼리 사이에 발생하면 totals와 top 목록이 서로 다른 집계 결과를 보게 된다.

권장 수정:

1. overview의 네 조회를 repeatable-read, read-only 트랜잭션으로 실행한다.
2. 또는 하나의 SQL/CTE에서 동일한 스냅샷으로 totals와 순위를 계산한다.
3. 집계 UPSERT와 overview 조회를 교차 실행해 응답 내부의 합계와 목록이 같은 스냅샷을 쓰는지
   검증하는 통합 테스트를 추가한다.

## P2 — 문서화한 공통 필터와 실제 API가 다르고 날짜 범위가 하루씩 넓음

문서는 모든 사용량 API가 `team_id`, `user_id`, `virtual_key_id`, `model_alias`를 공통
파라미터로 받는다고 정의한다. 그러나 overview는 `virtual_key_id`를 받지 않고,
auth-events는 `AuthEvent.model_alias` 열이 존재함에도 `model_alias`를 받지 않는다. 필터를
이용한 drill-down 계약을 만족하지 못한다.

또한 기본값은 “최근 30일”이라고 되어 있지만 시작일을 `today - 30 days`로 잡고 양끝을
포함하므로 31일을 조회한다. 최대 366일 검증도 날짜 차이만 비교해 양끝 포함 367일 범위를
허용한다.

권장 수정:

1. overview에 `virtual_key_id`, auth-events에 `model_alias`를 추가해 문서의 공통 필터 계약을
   맞춘다.
2. 기본 30일의 시작일은 `today - 29 days`로 설정하고, 최대 범위는 포함 일수
   `(to_date - from_date).days + 1`로 검증한다.
3. 각 endpoint의 OpenAPI 파라미터와 문서의 공통 파라미터를 대조하는 API 테스트를 추가한다.

## 검증 범위

- `ruff check src tests` 통과
- 전체 단위 테스트 182개 통과
- M7 변경의 `git diff --check` 통과

현재 테스트는 정책 함수, 인가 범위, 오프라인 SQL 렌더링에 집중되어 있다. 실제 PostgreSQL
원천 이벤트를 이용한 backfill·지연 도착·부분 월 trend·동시 집계와 조회의 스냅샷 일관성은
검증하지 않는다.
