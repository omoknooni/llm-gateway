'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import type { ActionResult } from '@/lib/actions/types';

/**
 * Server Action 호출 래퍼.
 *
 * 화면마다 반복되는 세 가지를 한 곳에 모읍니다.
 *  - 진행 중 상태
 *  - 실패 시 토스트 + `request_id` 노출 (00 문서 Error Contract)
 *  - 필드 단위 검증 오류를 폼에 되돌리기
 *
 * 성공 후 `router.refresh()` 를 부르는 이유는 Server Action 의 `revalidatePath` 가 캐시를
 * 무효화할 뿐 현재 열려 있는 화면을 다시 그리지는 않기 때문입니다.
 */
export function useAction<TArgs extends unknown[], TData>(
  fn: (...args: TArgs) => Promise<ActionResult<TData>>,
  options: {
    successMessage?: string;
    onSuccess?: (data: TData) => void;
    /** 실패해도 토스트를 띄우지 않고 호출자가 직접 처리합니다. */
    silentError?: boolean;
  } = {},
) {
  const [pending, setPending] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const toast = useToast();
  const router = useRouter();

  const run = useCallback(
    async (...args: TArgs): Promise<ActionResult<TData>> => {
      setPending(true);
      setFieldErrors({});
      try {
        const result = await fn(...args);
        if (result.ok) {
          if (options.successMessage) toast.success(options.successMessage);
          options.onSuccess?.(result.data);
          router.refresh();
        } else {
          setFieldErrors(result.fieldErrors ?? {});
          if (!options.silentError) toast.error(result.message, result.requestId);
        }
        return result;
      } finally {
        setPending(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fn, options.successMessage, options.silentError, router, toast],
  );

  return { run, pending, fieldErrors, clearFieldErrors: () => setFieldErrors({}) };
}
