'use client';

import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/cn';

/** 값 복사. UUID·prefix·원문 키처럼 손으로 옮겨적기 어려운 값 옆에 붙입니다. */
export function CopyButton({
  value,
  label = '복사',
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // 클립보드 권한이 없으면 조용히 넘어갑니다. 값 자체는 화면에 이미 보입니다.
        }
      }}
      className={cn(
        'inline-flex items-center gap-1 rounded-(--radius-base) px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-surface-muted hover:text-foreground',
        className,
      )}
    >
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
      {copied ? '복사됨' : label}
    </button>
  );
}

/** 등폭으로 보여주는 식별자 + 복사 버튼. 목록에서는 앞 8자만 노출합니다. */
export function MonoId({ value, truncate = true }: { value: string; truncate?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      <code className="font-mono text-xs">{truncate ? value.slice(0, 8) : value}</code>
      <CopyButton value={value} label="" />
    </span>
  );
}
