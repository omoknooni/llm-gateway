'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/**
 * 모달. 포커스 트랩·ESC·스크롤 잠금은 Radix 에 맡깁니다.
 *
 * 직접 만들면 반드시 어딘가에서 포커스가 배경으로 새어 나갑니다.
 */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title,
  description,
  children,
  footer,
  className,
  /** 닫기 수단을 제한합니다. 원문 노출처럼 "확인했다"가 필요한 다이얼로그에 씁니다. */
  dismissible = true,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
  dismissible?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-[1px]" />
      <DialogPrimitive.Content
        onPointerDownOutside={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        className={cn(
          'fixed top-1/2 left-1/2 z-50 w-[min(92vw,34rem)] max-h-[88vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-(--radius-card) border border-border bg-surface shadow-xl',
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <DialogPrimitive.Title className="text-sm font-semibold">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-xs text-muted-foreground">
                {description}
              </DialogPrimitive.Description>
            ) : null}
          </div>
          {dismissible ? (
            <DialogPrimitive.Close
              className="-mr-1 rounded-(--radius-base) p-1 text-muted-foreground hover:bg-surface-muted hover:text-foreground"
              aria-label="닫기"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          ) : null}
        </div>
        <div className="px-4 py-4">{children}</div>
        {footer ? (
          <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
            {footer}
          </div>
        ) : null}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
