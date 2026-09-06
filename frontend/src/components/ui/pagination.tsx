'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

import { cn } from '@/lib/cn';
import { buildPaginationHrefs } from '@/lib/cursor';

/** 커서 페이지네이션. URL 계산 규칙은 `lib/cursor.ts` 에 있고 테스트로 고정되어 있습니다. */
export function CursorPagination({
  nextCursor,
  hasMore,
  className,
}: {
  nextCursor: string | null;
  hasMore: boolean;
  className?: string;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const { previous, next } = buildPaginationHrefs(
    pathname,
    new URLSearchParams(searchParams.toString()),
    { nextCursor, hasMore },
  );

  if (!previous && !next) return null;

  return (
    <div className={cn('flex items-center justify-end gap-2', className)}>
      <PageLink href={previous} direction="prev" />
      <PageLink href={next} direction="next" />
    </div>
  );
}

function PageLink({ href, direction }: { href: string | null; direction: 'prev' | 'next' }) {
  const label = direction === 'prev' ? '이전' : '다음';
  const Icon = direction === 'prev' ? ChevronLeft : ChevronRight;
  const base =
    'inline-flex h-8 items-center gap-1 rounded-(--radius-base) border border-border px-2.5 text-xs';

  if (!href) {
    return (
      <span className={cn(base, 'text-muted-foreground opacity-45')} aria-disabled="true">
        {direction === 'prev' ? <Icon className="size-3.5" /> : null}
        {label}
        {direction === 'next' ? <Icon className="size-3.5" /> : null}
      </span>
    );
  }

  return (
    <Link href={href} className={cn(base, 'hover:bg-surface-muted')}>
      {direction === 'prev' ? <Icon className="size-3.5" /> : null}
      {label}
      {direction === 'next' ? <Icon className="size-3.5" /> : null}
    </Link>
  );
}
