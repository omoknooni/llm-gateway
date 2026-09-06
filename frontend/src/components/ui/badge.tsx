import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';
import type { Tone } from '@/lib/format/labels';

/**
 * 상태 배지. 색은 토큰에서만 가져옵니다.
 *
 * 톤 매핑은 `lib/format/labels.ts` 한 곳에 있습니다. 화면마다 색을 정하면 같은 상태가
 * 표마다 다른 색으로 보입니다.
 */
const TONE_CLASS: Record<Tone, string> = {
  neutral: 'bg-surface-muted text-muted-foreground border-border',
  success: 'bg-success-soft text-success border-success/25',
  warning: 'bg-warning-soft text-warning border-warning/25',
  danger: 'bg-danger-soft text-danger border-danger/25',
  info: 'bg-info-soft text-info border-info/25',
};

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
