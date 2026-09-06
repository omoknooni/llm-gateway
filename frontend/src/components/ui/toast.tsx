'use client';

import * as ToastPrimitive from '@radix-ui/react-toast';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

type ToastKind = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
  /** backend 로그를 찾는 유일한 열쇠입니다. 실패 토스트에는 항상 싣습니다. */
  requestId?: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string, requestId?: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error('useToast 는 ToastProvider 안에서만 쓸 수 있습니다');
  return api;
}

const KIND_STYLE: Record<ToastKind, { icon: typeof Info; className: string }> = {
  success: { icon: CheckCircle2, className: 'border-success/35 bg-success-soft text-success' },
  error: { icon: AlertTriangle, className: 'border-danger/35 bg-danger-soft text-danger' },
  info: { icon: Info, className: 'border-border bg-surface text-foreground' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((item: Omit<ToastItem, 'id'>) => {
    setItems((current) => [...current, { ...item, id: Date.now() + Math.random() }]);
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push({ kind: 'success', message }),
      error: (message, requestId) => push({ kind: 'error', message, requestId }),
      info: (message) => push({ kind: 'info', message }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
        {children}
        {items.map((item) => {
          const { icon: Icon, className } = KIND_STYLE[item.kind];
          return (
            <ToastPrimitive.Root
              key={item.id}
              onOpenChange={(open) => {
                if (!open) setItems((current) => current.filter((entry) => entry.id !== item.id));
              }}
              className={cn(
                'flex items-start gap-2.5 rounded-(--radius-card) border px-3 py-2.5 shadow-lg',
                'data-[state=closed]:opacity-0 data-[state=open]:animate-in',
                className,
              )}
            >
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <ToastPrimitive.Description className="text-sm break-words">
                  {item.message}
                </ToastPrimitive.Description>
                {item.requestId ? (
                  <p className="mt-1 font-mono text-[11px] opacity-70">
                    request_id: {item.requestId}
                  </p>
                ) : null}
              </div>
              <ToastPrimitive.Close aria-label="닫기" className="shrink-0 opacity-60 hover:opacity-100">
                <X className="size-3.5" />
              </ToastPrimitive.Close>
            </ToastPrimitive.Root>
          );
        })}
        <ToastPrimitive.Viewport className="fixed right-4 bottom-4 z-100 flex w-[min(92vw,24rem)] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
