/**
 * 금액 표시.
 *
 * backend 는 금액을 **문자열**로 직렬화합니다. JSON number 로 받으면 프론트에서 float 이 되어
 * `0.0003` 같은 단가의 정밀도가 깨집니다(AGENTS.md 공통 규약, backend 00 문서).
 *
 * 그래서 여기의 모든 함수는 **문자열을 문자열로** 다룹니다. 중간에 `Number()`가 끼면
 * 규약이 무너지므로 쓰지 않습니다.
 */

/** 부호·정수부·소수부로 쪼갭니다. 숫자로 파싱하지 않습니다. */
function split(value: string): { sign: string; int: string; frac: string } | null {
  const trimmed = value.trim();
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(trimmed);
  if (!match || (!match[2] && !match[3])) return null;
  return {
    sign: match[1] === '-' ? '-' : '',
    int: match[2] || '0',
    frac: match[3] ?? '',
  };
}

function groupThousands(int: string): string {
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export interface DecimalFormatOptions {
  /** 최소 소수 자릿수. 부족하면 0 으로 채웁니다. */
  minFractionDigits?: number;
  /** 최대 소수 자릿수. 넘치면 **버립니다**(반올림하지 않습니다 — 표시용이므로 값을 키우지 않습니다). */
  maxFractionDigits?: number;
  /** 천 단위 구분 쉼표. */
  grouping?: boolean;
}

/**
 * 문자열 금액을 표시용 문자열로 다듬습니다. 파싱 불가면 원본을 그대로 돌려줍니다 —
 * 알 수 없는 값을 `0` 으로 바꿔 보여주는 것이 가장 나쁜 실패입니다.
 */
export function formatDecimal(value: string, options: DecimalFormatOptions = {}): string {
  const { minFractionDigits = 0, maxFractionDigits = 10, grouping = true } = options;
  const parts = split(value);
  if (!parts) return value;

  let frac = parts.frac.slice(0, maxFractionDigits);
  frac = frac.replace(/0+$/, '');
  while (frac.length < minFractionDigits) frac += '0';

  const int = grouping ? groupThousands(parts.int) : parts.int;
  return frac ? `${parts.sign}${int}.${frac}` : `${parts.sign}${int}`;
}

/** `$0.003` — 1K 토큰 단가. 소수 자릿수를 잘라내지 않습니다. */
export function formatUsdPrice(value: string, currency = 'USD'): string {
  const symbol = currency === 'USD' ? '$' : '';
  return `${symbol}${formatDecimal(value, { minFractionDigits: 2, maxFractionDigits: 8 })}`;
}
