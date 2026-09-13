import { describe, expect, it } from 'vitest';

import {
  DEFAULT_RANGE_DAYS,
  bucketsInRange,
  fillTrend,
  isBudgetUnset,
  normalizePeriod,
  normalizeRange,
  parseThresholds,
  rangeDays,
  recentPeriods,
} from '@/lib/format/usage';
import { TrendGranularity, type UsageTotals } from '@/types/api';

const NOW = new Date('2026-09-12T09:00:00Z');

const TOTALS: UsageTotals = {
  request_count: 3,
  success_count: 3,
  error_count: 0,
  input_tokens: 10,
  output_tokens: 20,
  total_tokens: 30,
  cache_write_tokens: 0,
  cache_read_tokens: 0,
  estimated_cost_usd: '1.2345',
  failure_rate_pct: '0.00',
  avg_latency_ms: 120,
};

describe('조회 기간', () => {
  it('양끝을 포함해 센다', () => {
    // 날짜 차이로 세면 "최근 30일"이 31일을 조회합니다. backend 와 같은 규칙입니다.
    expect(rangeDays({ from: '2026-09-01', to: '2026-09-01' })).toBe(1);
    expect(rangeDays({ from: '2026-09-01', to: '2026-09-30' })).toBe(30);
  });

  it('기본 기간의 시작일은 오늘 - (N-1) 이다', () => {
    const range = normalizeRange(undefined, undefined, NOW);
    expect(range.to).toBe('2026-09-12');
    expect(rangeDays(range)).toBe(DEFAULT_RANGE_DAYS);
  });

  it('형식이 깨졌거나 뒤집혔거나 상한을 넘으면 기본 기간으로 되돌린다', () => {
    const fallback = normalizeRange(undefined, undefined, NOW);
    expect(normalizeRange('2026-13-99', '2026-09-12', NOW)).toEqual(fallback);
    expect(normalizeRange('2026-09-12', '2026-09-01', NOW)).toEqual(fallback);
    // 367일은 backend 상한(366) 밖입니다.
    expect(normalizeRange('2025-09-11', '2026-09-12', NOW)).toEqual(fallback);
    // 366일 정확히는 통과해야 합니다.
    expect(normalizeRange('2025-09-12', '2026-09-12', NOW)).toEqual({
      from: '2025-09-12',
      to: '2026-09-12',
    });
  });
});

describe('예산 기간', () => {
  it('UTC 월을 씁니다 — KST 로 옮기면 gateway 카운터와 다른 월을 본다', () => {
    // KST 기준이면 2026-09-13 이지만 UTC 로는 아직 9월 12일 15시입니다.
    expect(normalizePeriod(undefined, new Date('2026-09-12T15:00:00Z'))).toBe('2026-09');
    expect(normalizePeriod(undefined, new Date('2026-12-31T15:00:00Z'))).toBe('2026-12');
  });

  it('형식이 깨진 값은 현재 월로 되돌린다', () => {
    expect(normalizePeriod('2026-13', NOW)).toBe('2026-09');
    expect(normalizePeriod('2026-9', NOW)).toBe('2026-09');
    expect(normalizePeriod('2026-07', NOW)).toBe('2026-07');
  });

  it('최근 기간 목록은 연 경계를 넘어간다', () => {
    expect(recentPeriods(3, new Date('2026-01-15T00:00:00Z'))).toEqual([
      '2026-01',
      '2025-12',
      '2025-11',
    ]);
  });
});

describe('추이 버킷', () => {
  it('일 버킷은 기간 전체를 채운다', () => {
    expect(bucketsInRange({ from: '2026-08-30', to: '2026-09-02' }, TrendGranularity.DAY)).toEqual([
      '2026-08-30',
      '2026-08-31',
      '2026-09-01',
      '2026-09-02',
    ]);
  });

  it('월 버킷은 기간이 걸치는 달을 모두 낸다', () => {
    expect(
      bucketsInRange({ from: '2025-11-20', to: '2026-01-05' }, TrendGranularity.MONTH),
    ).toEqual(['2025-11', '2025-12', '2026-01']);
  });

  it('값이 없는 버킷은 0 이 아니라 null 이다', () => {
    // "집계가 아직 안 돈 날"과 "호출이 없던 날"은 다릅니다. 0 으로 채우면 구분이 사라집니다.
    const filled = fillTrend(
      [{ bucket: '2026-09-02', totals: TOTALS }],
      { from: '2026-09-01', to: '2026-09-03' },
      TrendGranularity.DAY,
    );
    expect(filled.map((bucket) => bucket.bucket)).toEqual([
      '2026-09-01',
      '2026-09-02',
      '2026-09-03',
    ]);
    expect(filled[0]?.totals).toBeNull();
    expect(filled[1]?.totals).toBe(TOTALS);
    expect(filled[2]?.totals).toBeNull();
  });
});

describe('예산 미설정 판정', () => {
  it('미설정(무제한)과 한도 0(쓸 수 없음)을 구분한다', () => {
    // backend 는 미설정일 때 limit 0 + SOFT_WARN + NORMAL 로 내려줍니다(05 문서).
    expect(
      isBudgetUnset({ limit_usd: '0', policy: 'SOFT_WARN', alert_level: 'NORMAL' }),
    ).toBe(true);
    // 한도 0 에 소진이 있으면 backend 가 100% · EXCEEDED 로 계산합니다.
    expect(
      isBudgetUnset({ limit_usd: '0', policy: 'HARD_BLOCK', alert_level: 'EXCEEDED' }),
    ).toBe(false);
    expect(
      isBudgetUnset({ limit_usd: '1000.0000', policy: 'HARD_BLOCK', alert_level: 'NORMAL' }),
    ).toBe(false);
  });
});

describe('경보 임계 입력', () => {
  it('범위를 벗어나거나 정수가 아닌 값은 버린다', () => {
    expect(parseThresholds('80, 90,100')).toEqual([80, 90, 100]);
    expect(parseThresholds('0,80,1001,abc,50.5')).toEqual([80]);
  });
});
