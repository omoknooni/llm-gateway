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

/**
 * `$1,234.56` — 합계 금액. 단가(`formatUsdPrice`)와 자릿수를 다르게 씁니다.
 *
 * 단가는 `0.00003` 같은 값이라 8 자리까지 살려야 하지만, 소진액·비용 합계를 그 자릿수로
 * 보여주면 읽을 수 없습니다. **값은 문자열 그대로이고 잘라내기만 합니다**(반올림 없음).
 */
export function formatUsd(value: string, currency = 'USD'): string {
  const symbol = currency === 'USD' ? '$' : '';
  return `${symbol}${formatDecimal(value, { minFractionDigits: 2, maxFractionDigits: 2 })}`;
}

/**
 * 금액 문자열을 **1/10000 단위 정수**로 옮깁니다(backend `numeric(14,4)` 와 같은 눈금).
 *
 * 배분 합계를 미리 보여주려면 더하기가 필요한데, `Number` 로 더하면 `0.1 + 0.2` 가
 * `0.30000000000000004` 가 됩니다. 한도와 합계가 같은지 묻는 화면에서 이런 차이는 그대로
 * 잘못된 경고가 됩니다. 형식이 깨진 값은 `null` 입니다.
 */
const MONEY_SCALE = 4n;

function toUnits(value: string): bigint | null {
  const parts = split(value);
  if (!parts) return null;
  const frac = (parts.frac + '0'.repeat(Number(MONEY_SCALE))).slice(0, Number(MONEY_SCALE));
  // 소수 4자리를 넘는 입력은 표현할 수 없습니다. 잘라서 합산하면 화면 합계가 조용히 달라집니다.
  if (parts.frac.length > Number(MONEY_SCALE)) return null;
  return BigInt(`${parts.sign}${parts.int}${frac}`);
}

function fromUnits(units: bigint): string {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(5, '0');
  const int = digits.slice(0, -4);
  const frac = digits.slice(-4).replace(/0+$/, '');
  return `${negative ? '-' : ''}${int}${frac ? `.${frac}` : ''}`;
}

/** 금액 문자열의 합. 하나라도 형식이 깨지면 `null` 입니다. */
export function sumDecimals(values: string[]): string | null {
  let total = 0n;
  for (const value of values) {
    const units = toUnits(value);
    if (units === null) return null;
    total += units;
  }
  return fromUnits(total);
}

/** `a - b` 의 부호. `null` 이면 비교할 수 없는 값입니다. */
export function compareDecimals(a: string, b: string): number | null {
  const left = toUnits(a);
  const right = toUnits(b);
  if (left === null || right === null) return null;
  return left === right ? 0 : left > right ? 1 : -1;
}
