/**
 * 사용량·예산 표시 보조.
 *
 * 금액은 `format/decimal.ts` 가 문자열 그대로 다룹니다. 여기는 **개수·기간·버킷**만 다룹니다.
 *
 * 기간 경계는 backend 와 같은 **UTC** 입니다(backend 05·10 문서). 표시만 KST 이고, 조회
 * 파라미터를 KST 로 만들면 예산 소진액과 사용량 비용이 서로 다른 월을 보게 됩니다.
 */

import type { TrendGranularity, UsageTotals } from '@/types/api';

/** 기본 조회 기간(일). 양끝을 포함하므로 시작일은 `오늘 - (N-1)` 입니다. */
export const DEFAULT_RANGE_DAYS = 30;

/** backend 상한과 같습니다(`date_range_too_wide`). 넘으면 요청 전에 막습니다. */
export const MAX_RANGE_DAYS = 366;

const DAY_MS = 86_400_000;

/** `YYYY-MM-DD` (UTC). `<input type="date">` 값과 같은 형식입니다. */
export function toUtcDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

/** 현재 월 `YYYY-MM` (UTC). 예산 기간의 기본값입니다. */
export function currentPeriod(now = new Date()): string {
  return now.toISOString().slice(0, 7);
}

/** 최근 N개월 `YYYY-MM` 목록(최신순). 기간 선택 드롭다운에 씁니다. */
export function recentPeriods(count: number, now = new Date()): string[] {
  const periods: string[] = [];
  for (let index = 0; index < count; index += 1) {
    const cursor = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - index, 1));
    periods.push(cursor.toISOString().slice(0, 7));
  }
  return periods;
}

export interface DateRange {
  from: string;
  to: string;
}

/** 기본 조회 기간. 양끝 포함 N일입니다. */
export function defaultRange(now = new Date()): DateRange {
  return {
    from: toUtcDate(new Date(now.getTime() - (DEFAULT_RANGE_DAYS - 1) * DAY_MS)),
    to: toUtcDate(now),
  };
}

/** 양끝을 포함한 일수. 날짜 차이로 세면 하루 좁아집니다. */
export function rangeDays(range: DateRange): number {
  const from = Date.parse(`${range.from}T00:00:00Z`);
  const to = Date.parse(`${range.to}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return 0;
  return Math.floor((to - from) / DAY_MS) + 1;
}

/**
 * 조회 파라미터로 쓸 기간. 형식이 깨졌거나 뒤집혔거나 상한을 넘으면 기본 기간으로 되돌립니다.
 *
 * backend 도 같은 검증을 하지만, 여기서 걸러 두면 URL 을 손으로 고친 경우에 화면이 422 로
 * 죽는 대신 기본값으로 뜹니다.
 */
export function normalizeRange(
  from: string | undefined,
  to: string | undefined,
  now = new Date(),
): DateRange {
  const fallback = defaultRange(now);
  if (!from || !to || !/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    return fallback;
  }
  const range = { from, to };
  const days = rangeDays(range);
  if (days <= 0 || days > MAX_RANGE_DAYS) return fallback;
  return range;
}

/** `2026-09` 형식 검증. 잘못된 값이면 현재 월로 되돌립니다. */
export function normalizePeriod(period: string | undefined, now = new Date()): string {
  return period && /^\d{4}-(0[1-9]|1[0-2])$/.test(period) ? period : currentPeriod(now);
}

/** 기간이 걸치는 버킷 이름(오름차순). `DAY` 는 `YYYY-MM-DD`, `MONTH` 는 `YYYY-MM`. */
export function bucketsInRange(range: DateRange, granularity: TrendGranularity): string[] {
  const buckets: string[] = [];
  const from = new Date(`${range.from}T00:00:00Z`);
  const to = new Date(`${range.to}T00:00:00Z`);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || from > to) return buckets;

  if (granularity === 'MONTH') {
    let cursor = new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), 1));
    const last = Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), 1);
    while (cursor.getTime() <= last) {
      buckets.push(cursor.toISOString().slice(0, 7));
      cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
    }
    return buckets;
  }

  for (let time = from.getTime(); time <= to.getTime(); time += DAY_MS) {
    buckets.push(new Date(time).toISOString().slice(0, 10));
  }
  return buckets;
}

export interface FilledBucket {
  bucket: string;
  /** 값이 없는 버킷은 `null` 입니다. **0 과 구분됩니다** — 집계가 안 돈 날일 수 있습니다. */
  totals: UsageTotals | null;
}

/**
 * 추이 응답을 기간 전체로 펼칩니다.
 *
 * backend 는 값이 없는 버킷의 행을 만들지 않습니다(빈 것과 0 은 다르므로). 기간을 아는 쪽은
 * 화면이라 채우기도 화면이 합니다. 다만 **0 으로 채우지 않고 `null` 로 둡니다** — 막대를
 * 0 높이로 그릴지, 구멍으로 그릴지는 그리는 쪽이 정합니다.
 */
export function fillTrend(
  points: { bucket: string; totals: UsageTotals }[],
  range: DateRange,
  granularity: TrendGranularity,
): FilledBucket[] {
  const byBucket = new Map(points.map((point) => [point.bucket, point.totals]));
  return bucketsInRange(range, granularity).map((bucket) => ({
    bucket,
    totals: byBucket.get(bucket) ?? null,
  }));
}

const COUNT_FORMAT = new Intl.NumberFormat('ko-KR');

/** 호출 수·토큰 수. 정수라 number 로 다뤄도 정밀도 문제가 없습니다(금액과 다릅니다). */
export function formatCount(value: number): string {
  return COUNT_FORMAT.format(value);
}

/** `12.34%`. 값은 backend 가 준 문자열 그대로이고 여기서 다시 계산하지 않습니다. */
export function formatPercent(value: string, suffix = '%'): string {
  return `${value}${suffix}`;
}

/** `1,234ms`. 버킷 간 합성은 backend 가 호출 수로 가중해 계산합니다. */
export function formatLatency(ms: number): string {
  return `${COUNT_FORMAT.format(ms)}ms`;
}

/**
 * 예산 미설정(= 무제한) 판정.
 *
 * backend 는 설정이 없을 때 `limit_usd=0`, `policy=SOFT_WARN`, `alert_level=NORMAL` 로
 * 내려줍니다(05 문서 `_single_item`). **한도 0 은 "쓸 수 없음"이고 미설정과 다르므로**
 * 화면이 둘을 같은 문구로 보여주면 안 됩니다.
 *
 * ponytail: 한도 0·소진 0·SOFT_WARN 인 실제 설정과는 구분되지 않습니다. 구분이 필요해지면
 * backend 응답에 `configured` 플래그를 요청하는 것이 맞습니다 — 화면에서 더 추측하지 않습니다.
 */
export function isBudgetUnset(item: {
  limit_usd: string;
  policy: string;
  alert_level: string;
}): boolean {
  return Number(item.limit_usd) === 0 && item.policy === 'SOFT_WARN' && item.alert_level === 'NORMAL';
}

/** `80,90,100` → `[80, 90, 100]`. 형식이 깨진 값은 버립니다(backend 가 다시 검증합니다). */
export function parseThresholds(raw: string): number[] {
  return raw
    .split(',')
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isInteger(value) && value > 0 && value <= 1000);
}
