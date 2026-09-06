'use client';

import { AlertTriangle } from 'lucide-react';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';

/**
 * 전역 에러 경계.
 *
 * Next 는 프로덕션에서 서버 예외 메시지를 지우고 `digest` 만 남깁니다. 그래서 원인을 찾는
 * 실마리는 digest 와 backend 의 `request_id` 두 개뿐입니다. 화면에 그대로 보여줍니다.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('console.unhandled', error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <AlertTriangle className="mx-auto size-8 text-danger" />
        <h1 className="mt-3 text-lg font-semibold">화면을 불러오지 못했습니다</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
        {error.digest ? (
          <p className="mt-1 font-mono text-xs text-muted-foreground">digest: {error.digest}</p>
        ) : null}
        <Button variant="secondary" className="mt-4" onClick={reset}>
          다시 시도
        </Button>
      </div>
    </div>
  );
}
