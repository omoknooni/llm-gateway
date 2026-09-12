import { describe, expect, it } from 'vitest';

import {
  compareDecimals,
  formatDecimal,
  formatUsd,
  formatUsdPrice,
  sumDecimals,
} from '@/lib/format/decimal';

/**
 * 금액은 backend 가 문자열로 직렬화합니다. 표시 포맷을 거쳐도 정밀도가 유지되어야 합니다.
 * `Number()` 가 한 번이라도 끼면 여기서 깨집니다(AGENTS.md 금액 규약).
 */
describe('formatDecimal', () => {
  it('float 로 바꿨다면 깨졌을 자릿수를 그대로 유지한다', () => {
    expect(formatDecimal('0.000000000000000000001', { maxFractionDigits: 30 })).toBe(
      '0.000000000000000000001',
    );
    expect(formatDecimal('9007199254740993', { grouping: false })).toBe('9007199254740993');
    expect(formatDecimal('0.1', { maxFractionDigits: 20 })).toBe('0.1');
  });

  it('의미 없는 뒷자리 0 만 떼고 최소 자릿수는 채운다', () => {
    expect(formatDecimal('1.2300', { minFractionDigits: 2 })).toBe('1.23');
    expect(formatDecimal('2', { minFractionDigits: 2 })).toBe('2.00');
    expect(formatDecimal('2.000', { minFractionDigits: 0 })).toBe('2');
  });

  it('최대 자릿수를 넘으면 반올림하지 않고 버린다', () => {
    // 표시용이므로 값을 키우지 않습니다. 0.999 를 1 로 보여주면 단가를 잘못 읽습니다.
    expect(formatDecimal('0.9999', { maxFractionDigits: 2 })).toBe('0.99');
  });

  it('천 단위 구분은 정수부에만 붙는다', () => {
    expect(formatDecimal('1234567.891')).toBe('1,234,567.891');
  });

  it('파싱할 수 없는 값은 0 으로 바꾸지 않고 원본을 돌려준다', () => {
    expect(formatDecimal('N/A')).toBe('N/A');
    expect(formatDecimal('')).toBe('');
  });

  it('음수 부호를 잃지 않는다', () => {
    expect(formatDecimal('-12.50', { minFractionDigits: 2 })).toBe('-12.50');
  });
});

describe('formatUsdPrice', () => {
  it('1K 토큰 단가의 유효 자릿수를 자르지 않는다', () => {
    expect(formatUsdPrice('0.00025')).toBe('$0.00025');
    expect(formatUsdPrice('3')).toBe('$3.00');
  });
});

/**
 * 배분 합계는 "한도를 넘었는가"를 묻는 자리입니다. float 로 더하면 넘지 않은 합계가
 * 넘은 것으로 보입니다 — 잘못된 경고는 잘못된 값만큼 나쁩니다.
 */
describe('sumDecimals', () => {
  it('float 이었다면 어긋났을 합을 정확히 낸다', () => {
    expect(sumDecimals(['0.1', '0.2'])).toBe('0.3');
    expect(Number('0.1') + Number('0.2')).not.toBe(0.3);
    expect(sumDecimals(['1000.0001', '2000.9999'])).toBe('3001');
  });

  it('빈 목록은 0 이다', () => {
    expect(sumDecimals([])).toBe('0');
  });

  it('표현할 수 없는 값은 합치지 않고 null 을 낸다', () => {
    // 소수 5자리는 backend 의 numeric(14,4) 에 담기지 않습니다. 잘라서 더하면 화면 합계가
    // 저장될 값과 달라집니다.
    expect(sumDecimals(['1.00001'])).toBeNull();
    expect(sumDecimals(['1.0', 'abc'])).toBeNull();
  });
});

describe('compareDecimals', () => {
  it('한도와 합계를 자릿수 그대로 비교한다', () => {
    expect(compareDecimals('1000.0000', '1000')).toBe(0);
    expect(compareDecimals('1000.0001', '1000')).toBe(1);
    expect(compareDecimals('999.9999', '1000')).toBe(-1);
    expect(compareDecimals('x', '1000')).toBeNull();
  });
});

describe('formatUsd', () => {
  it('합계 금액은 두 자리로 자른다 (반올림하지 않는다)', () => {
    expect(formatUsd('1234.5678')).toBe('$1,234.56');
    expect(formatUsd('0')).toBe('$0.00');
  });
});
