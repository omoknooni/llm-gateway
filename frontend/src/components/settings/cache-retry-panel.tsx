'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { retryCacheInvalidationAction } from '@/lib/actions/cache';
import { useAction } from '@/lib/use-action';

/**
 * 캐시 무효화 재시도.
 *
 * control plane 은 정책 캐시를 **삭제만** 합니다. 값을 채우는 주체는 gateway 입니다
 * (AGENTS.md 캐시 소유권). 무효화 실패의 영향은 "정책 반영 지연"이지 "영구 불일치"가
 * 아닙니다 — TTL 이 만료되면 gateway 가 스스로 최신 값을 읽습니다.
 */
export function CacheRetryPanel() {
  const [result, setResult] = useState<Record<string, number> | null>(null);

  const { run, pending } = useAction(retryCacheInvalidationAction, {
    successMessage: '재시도를 실행했습니다',
    onSuccess: setResult,
  });

  return (
    <Card>
      <CardHeader
        title="캐시 무효화 재시도"
        description="Redis 오류로 지우지 못하고 쌓인 무효화 작업을 다시 시도합니다."
        actions={
          <Button variant="primary" size="sm" loading={pending} onClick={() => void run()}>
            재시도 실행
          </Button>
        }
      />
      <CardBody>
        {result === null ? (
          <p className="text-sm text-muted-foreground">
            아직 실행하지 않았습니다. 팀 이동·사용자 비활성화 결과에서 &ldquo;캐시 무효화
            실패&rdquo; 를 봤다면 여기서 털어내세요.
          </p>
        ) : Object.keys(result).length === 0 ? (
          <p className="text-sm">미해결 항목이 없습니다.</p>
        ) : (
          <dl className="grid gap-2 sm:grid-cols-3">
            {Object.entries(result).map(([key, value]) => (
              <div key={key} className="rounded-(--radius-base) border border-border px-3 py-2">
                <dt className="text-xs text-muted-foreground">{key}</dt>
                <dd className="num mt-0.5 text-lg font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardBody>
    </Card>
  );
}
