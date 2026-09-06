import Link from 'next/link';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';
import type { Tone } from '@/lib/format/labels';

const TONE_VALUE: Record<Tone, string> = {
  neutral: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

/**
 * 지표 카드.
 *
 * `tone` 은 장식이 아니라 신호입니다. 값이 0 일 때는 중립으로, 조치가 필요할 때만 색을
 * 올리세요. 항상 빨간 카드는 아무도 보지 않게 됩니다.
 */
export function StatCard({
  label,
  value,
  hint,
  tone = 'neutral',
  href,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  href?: string;
}) {
  const body = (
    <>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('num mt-1.5 text-2xl font-semibold tracking-tight', TONE_VALUE[tone])}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </>
  );

  const className = 'block rounded-(--radius-card) border border-border bg-surface px-4 py-3.5';

  return href ? (
    <Link href={href} className={cn(className, 'transition-colors hover:bg-surface-muted')}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}
