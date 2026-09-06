import { cn } from '@/lib/cn';

import { Card } from './card';

/** 로딩 자리 표시. 화면이 흰 채로 비어 있는 것보다 구조가 보이는 편이 낫습니다. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-(--radius-base) bg-surface-muted', className)} />;
}

export function TableSkeleton({ rows = 8, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div>
      <Skeleton className="mb-5 h-8 w-48" />
      <Card>
        <div className="divide-y divide-[var(--border)]">
          {Array.from({ length: rows }).map((_, rowIndex) => (
            <div key={rowIndex} className="flex items-center gap-3 px-3 py-3">
              {Array.from({ length: columns }).map((_, columnIndex) => (
                <Skeleton
                  key={columnIndex}
                  className={cn('h-4', columnIndex === 0 ? 'w-40' : 'w-24')}
                />
              ))}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
