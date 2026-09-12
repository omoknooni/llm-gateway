# M7 리뷰 회신

| 항목 | 내용 |
|---|---|
| 대상 | [review.md](review.md) (`f3cca16` 검토) |
| 결론 | P1 2건·P2 2건 **모두 수용**. 수정 완료 |

## P1-1 lookback 밖 이벤트가 영구히 누락 — 수용, 수정

지적이 정확합니다. 되돌아보기 창은 "늦게 도착하는 이벤트"를 덮으려고 둔 것인데, 그 창을
**유일한 집계 경로**로 둔 것이 잘못이었습니다. M7 배포 시점에 이미 쌓여 있던 원천과 창보다
긴 장애 뒤에 들어온 이벤트가 어디에서도 집계되지 않습니다.

권장안 1(일회성 backfill)을 택했습니다.

- `app/jobs/backfill.py` — `python -m app.jobs.backfill [--since] [--until] [--dry-run]`.
  구간을 주지 않으면 **원천의 가장 이른 이벤트**부터 오늘까지입니다.
- 구간을 31일씩 쪼개 돕니다. 전 구간을 한 트랜잭션으로 처리하면 그동안 주기 job 이 막힙니다.
- 주기 집계와 **같은 advisory lock** 을 잡습니다. 결과는 멱등이라 같지만, 같은 버킷을 두
  트랜잭션이 동시에 UPSERT 하면 교착 가능성이 있습니다.
- `aggregate_usage_daily/monthly` 에 `since`/`until` 을 추가했습니다. 집계 경로는 하나로 두고
  구간만 밖에서 정합니다 — 경로가 둘이면 두 코드의 지표 정의가 갈립니다.

권장안 2(창을 gateway 보장 지연보다 길게)는 **택하지 않았습니다.** gateway 가 보장하는 지연
상한이 아직 계약에 없고, 값을 키우면 매 주기 스캔 비용이 그만큼 커집니다. 상한이 정해지면
그때 기본값을 조정하는 편이 낫습니다. 그 전까지 창은 "정상 운영의 지연"만 덮는 것으로 두고,
그 밖은 backfill 이 담당한다는 역할 분담을 [10](../../10-usage-aggregation.md)에 명시했습니다.

권장안 3(통합 테스트)은 4건 추가했습니다 — 창 밖 이벤트가 주기 집계에 안 잡히는 것,
backfill 이 최초 이벤트부터 가져오는 것, 주기 집계와 섞여도 멱등한 것, `--dry-run` 이 쓰지
않는 것.

## P1-2 부분 월 trend — 수용, 수정

명백한 버그입니다. `from_date=2026-09-15&to_date=2026-09-20` 에 9월 전체가 돌아왔습니다.

권장안 1 을 택했습니다. **월 trend 도 일 집계에서 만듭니다** — 정확한 일자 범위로 거른 뒤
`to_char(bucket_date, 'YYYY-MM')` 으로 묶습니다. 추이 응답에 p95 가 없으므로 합계와 가중
평균만으로 정확합니다.

권장안 2(양 끝은 일 집계, 가운데는 월 집계)는 택하지 않았습니다. 두 원천을 합치면 경계
조건이 늘고, 같은 숫자를 두 경로로 계산하게 됩니다. 월 집계 테이블은 **월 전체가 곧 기간**인
곳(예산 breakdown)에서만 쓰는 것으로 역할을 좁혔습니다.

권장안 3 대로 부분 월·여러 월·연도 경계 테스트를 넣었고, **trend 합계와 overview 합계가 같은
기간에서 일치하는지**도 확인합니다. 수정을 되돌리면 이 3건이 실패합니다.

## P2-1 overview 스냅샷 — 수용, 수정

주석이 코드가 제공하지 않는 보장을 주장하고 있었습니다. 지적대로 `READ COMMITTED` 에서는
SELECT 마다 새 스냅샷입니다.

권장안 1 을 택했습니다. overview 트랜잭션에 한해
`SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` 를 겁니다. 권장안 2(단일 CTE)는
네 조회가 서로 다른 GROUP BY 축이라 한 문장으로 묶으면 읽기 어려워지고, 축이 늘 때마다
그 문장을 고쳐야 합니다.

`SET TRANSACTION` 은 트랜잭션의 첫 문장이어야 하므로 실패할 수 있습니다. 그때는 **조용히 약한
보장으로 떨어지지 않고** 경고를 남깁니다.

권장안 3 대로, 합계 조회와 상위 목록 조회 **사이에** 집계를 커밋하는 테스트를 넣었습니다.
격리 수준을 끄면 실패합니다.

## P2-2 필터 계약 불일치와 날짜 범위 — 수용, 수정

셋 다 그대로입니다.

- overview 에 `virtual_key_id`, auth-events 에 `model_alias` 를 추가했습니다.
- 기본 기간 시작일을 `오늘 - 29` 로 바꿨습니다. "최근 30일"이 31일을 조회하고 있었습니다.
- 상한 검증을 포함 일수 `(to_date - from_date).days + 1` 로 바꿨습니다. 367일이 통과하고
  있었습니다. 거절 응답의 `details` 에 `requested_days` 를 실어 무엇이 넘쳤는지 보이게 했습니다.

권장안 3(OpenAPI 파라미터와 문서 대조 테스트)은 **부분만 했습니다.** 필터가 실제로 동작하는지를
통합 테스트로 확인하고(`virtual_key_id` → overview, `model_alias` → leaderboard), 기간 경계는
단위·통합 양쪽에 넣었습니다. OpenAPI 스펙과 문서 표를 기계적으로 대조하는 테스트는 만들지
않았습니다 — 문서 표를 파싱하는 테스트는 문서 서식이 바뀔 때마다 깨지고, 그 깨짐이 계약
위반을 뜻하지 않습니다. 대신 07 문서의 테스트 전략에 있는 **OpenAPI 스냅샷 비교**가 이 자리에
맞는 도구라고 보고, 아직 없는 그 항목을 남은 일로 둡니다.

## 검증

- `ruff check` 통과, 전체 **224개** 통과 (단위 183 + 통합 41)
- 리뷰 4건 모두, **수정을 되돌리면 해당 테스트가 실패하는 것**을 확인했습니다.

| 리뷰 | 테스트 |
|---|---|
| P1-1 | `test_usage_query.py::test_events_older_than_lookback_need_backfill` 외 3건 |
| P1-2 | `::test_month_trend_respects_partial_month_range` 외 2건 |
| P2-1 | `::test_overview_totals_and_top_lists_share_one_snapshot` |
| P2-2 | `::test_virtual_key_filter_applies_to_overview`, `::test_model_filter_applies_to_leaderboard`, `::test_date_range_boundaries_are_inclusive`, `test_usage_rules.py::test_too_wide_date_range_is_rejected` |

## 남은 것

- **OpenAPI 스냅샷 테스트** — 응답·파라미터 스키마 변경이 리뷰 diff 에 드러나게 하는 장치.
  07 문서의 테스트 전략에 "계약" 층으로 적혀 있지만 아직 없습니다.
- **라우터 계층 통합 테스트** — 현재 통합 테스트는 서비스·job·스키마 층입니다. 인가 분기가
  의존성과 서비스에 걸쳐 있어 HTTP 레벨 확인이 있으면 좋습니다.
- **gateway 지연 상한 계약** — 정해지면 `USAGE_AGGREGATION_LOOKBACK_DAYS` 기본값을 그에 맞춰
  조정합니다. 그 전까지는 backfill 이 안전망입니다.
