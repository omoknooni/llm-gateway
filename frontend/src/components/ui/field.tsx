import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/**
 * 폼 필드 래퍼.
 *
 * 라벨-입력-오류를 한 덩어리로 묶습니다. 오류는 필드 바로 아래에 붙습니다 — 폼 상단에
 * 모아 놓으면 어느 칸이 문제인지 알 수 없습니다.
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={htmlFor} className="block text-xs font-medium">
        {label}
        {required ? <span className="ml-0.5 text-danger">*</span> : null}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export const inputClass =
  'w-full rounded-(--radius-base) border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted-foreground disabled:opacity-50';

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputClass, className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputClass, 'min-h-20 resize-y', className)} {...props} />;
}

/**
 * 네이티브 select.
 *
 * 목록이 짧고 폼 안에 있을 때는 네이티브가 낫습니다. 모바일·키보드 동작이 공짜이고,
 * Server Action 의 FormData 에 그대로 실립니다. Radix Select 는 값 표시를 꾸며야 하는
 * 자리에만 씁니다.
 */
export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(inputClass, 'pr-8', className)} {...props} />;
}

export function Checkbox({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      className={cn('size-4 rounded-sm border-border accent-[var(--primary)]', className)}
      {...props}
    />
  );
}
