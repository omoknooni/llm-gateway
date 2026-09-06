import { LogOut } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { ThemeToggle } from '@/components/ui/theme-toggle';
import { USER_ROLE_LABEL, USER_ROLE_TONE } from '@/lib/format/labels';
import type { AdminSession } from '@/lib/auth/session';

export function Header({ session }: { session: AdminSession }) {
  return (
    <header className="flex h-13 shrink-0 items-center justify-end gap-3 border-b border-border bg-surface px-4">
      <div className="flex items-center gap-2">
        <span className="text-sm">{session.email}</span>
        <Badge tone={USER_ROLE_TONE[session.role]}>{USER_ROLE_LABEL[session.role]}</Badge>
        {/* 서비스 토큰으로 콘솔을 열고 있는 것은 비정상 상황입니다. 감추지 않습니다. */}
        {session.isServiceToken ? <Badge tone="warning">서비스 토큰</Badge> : null}
      </div>

      <ThemeToggle />

      <form method="POST" action="/api/auth/logout">
        <button
          type="submit"
          className="inline-flex size-8 items-center justify-center rounded-(--radius-base) text-muted-foreground hover:bg-surface-muted hover:text-foreground"
          aria-label="로그아웃"
        >
          <LogOut className="size-4" />
        </button>
      </form>
    </header>
  );
}
