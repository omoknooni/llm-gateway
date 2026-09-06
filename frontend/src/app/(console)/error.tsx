'use client';

import { AlertTriangle } from 'lucide-react';
import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';

/**
 * 콘솔 화면 에러 경계.
 *
 * Next 는 프로덕션에서 서버 예외 메시지를 지우고 `digest` 만 남깁니다. 그래서 여기서
 * 원인을 그대로 보여줄 수는 없고, **어디를 확인해야 하는지**를 알려주는 것이 최선입니다.
 * 정확한 코드와 `request_id` 는 서버 로그에 남아 있습니다.
 */
export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('console.page_failed', error);
  }, [error]);

  return (
    <Card className="mx-auto max-w-xl border-danger/35">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-danger" />
            화면을 불러오지 못했습니다
          </span>
        }
        description="Admin API 응답을 받지 못했거나 처리 중 오류가 났습니다."
      />
      <CardBody>
        <ul className="space-y-1.5 text-sm text-muted-foreground">
          <li>· Admin API 가 떠 있는지, `ADMIN_API_URL` 이 맞는지 확인하세요.</li>
          <li>· 세션이 만료되었다면 다시 로그인하면 해결됩니다.</li>
          <li>· 정확한 오류 코드와 `request_id` 는 콘솔 서버 로그에 남아 있습니다.</li>
        </ul>
        {error.digest ? (
          <p className="mt-3 font-mono text-xs text-muted-foreground">digest: {error.digest}</p>
        ) : null}
        <div className="mt-4 flex gap-2">
          <Button variant="primary" size="sm" onClick={reset}>
            다시 시도
          </Button>
          <Button variant="secondary" size="sm" asChild>
            <a href="/login">다시 로그인</a>
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
