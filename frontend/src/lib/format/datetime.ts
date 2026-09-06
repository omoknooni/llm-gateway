/**
 * 시간 표시.
 *
 * backend 응답은 ISO-8601 UTC 입니다. 화면은 KST 로 보여줍니다. 타임존을 고정하는 이유는
 * 서버 렌더와 브라우저 렌더가 다른 값을 내면 hydration 이 깨지기 때문입니다.
 */
const TIME_ZONE = 'Asia/Seoul';

const DATE_TIME = new Intl.DateTimeFormat('ko-KR', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const DATE_ONLY = new Intl.DateTimeFormat('ko-KR', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

function toParts(formatter: Intl.DateTimeFormat, iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const parts = Object.fromEntries(
    formatter.formatToParts(date).map((part) => [part.type, part.value]),
  );
  const ymd = `${parts['year']}-${parts['month']}-${parts['day']}`;
  return parts['hour'] ? `${ymd} ${parts['hour']}:${parts['minute']}` : ymd;
}

/** `2026-09-06 14:32` (KST). 값이 없으면 대시. */
export function formatDateTime(iso: string | null | undefined, fallback = '—'): string {
  if (!iso) return fallback;
  return toParts(DATE_TIME, iso) ?? fallback;
}

/** `2026-09-06` (KST). */
export function formatDate(iso: string | null | undefined, fallback = '—'): string {
  if (!iso) return fallback;
  return toParts(DATE_ONLY, iso) ?? fallback;
}

/** 지금부터 남은 일수. 음수면 이미 지난 시각입니다. */
export function daysUntil(iso: string | null | undefined, now = new Date()): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  return Math.ceil((target.getTime() - now.getTime()) / 86_400_000);
}

/** `3일 후 만료` / `2일 지남` 같은 짧은 문구. */
export function expiryHint(iso: string | null | undefined, now = new Date()): string | null {
  const days = daysUntil(iso, now);
  if (days === null) return null;
  if (days < 0) return `${Math.abs(days)}일 지남`;
  if (days === 0) return '오늘 만료';
  return `${days}일 후 만료`;
}

/** 지금으로부터 N일 뒤의 ISO 문자열. 목록 필터(만료 임박 등)에 씁니다. */
export function isoDaysFromNow(days: number, now = new Date()): string {
  return new Date(now.getTime() + days * 86_400_000).toISOString();
}

/** `<input type="datetime-local">` 이 요구하는 `YYYY-MM-DDTHH:mm` (KST 기준). */
export function toDateTimeLocalValue(iso: string, timeZone = TIME_ZONE): string {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date(iso)).map((part) => [part.type, part.value]),
  );
  const hour = parts['hour'] === '24' ? '00' : parts['hour'];
  return `${parts['year']}-${parts['month']}-${parts['day']}T${hour}:${parts['minute']}`;
}
