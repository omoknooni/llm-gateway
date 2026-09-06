import { describe, expect, it } from 'vitest';

import { daysUntil, expiryHint, formatDate, formatDateTime } from '@/lib/format/datetime';

describe('formatDateTime', () => {
  it('UTC 응답을 KST 로 옮긴다', () => {
    // 2026-09-06T15:30Z = 2026-09-07 00:30 KST — 날짜가 넘어가는 경계입니다.
    expect(formatDateTime('2026-09-06T15:30:00Z')).toBe('2026-09-07 00:30');
    expect(formatDate('2026-09-06T15:30:00Z')).toBe('2026-09-07');
  });

  it('값이 없거나 파싱할 수 없으면 폴백을 쓴다', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime(undefined, '기록 없음')).toBe('기록 없음');
    expect(formatDateTime('not-a-date')).toBe('—');
  });
});

describe('expiryHint', () => {
  const now = new Date('2026-09-06T00:00:00Z');

  it('남은 일수와 지난 일수를 구분한다', () => {
    expect(expiryHint('2026-09-09T00:00:00Z', now)).toBe('3일 후 만료');
    expect(expiryHint('2026-09-04T00:00:00Z', now)).toBe('2일 지남');
    expect(expiryHint('2026-09-06T00:00:00Z', now)).toBe('오늘 만료');
  });

  it('만료가 없으면 아무 문구도 만들지 않는다', () => {
    expect(expiryHint(null, now)).toBeNull();
    expect(daysUntil(null, now)).toBeNull();
  });
});
