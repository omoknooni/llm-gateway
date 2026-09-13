'use client';

import {
  Boxes,
  ChartColumn,
  Gauge,
  KeyRound,
  LayoutDashboard,
  Settings,
  UserRound,
  Users,
  Wallet,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/cn';
import { canAccessPath } from '@/lib/auth/permissions';
import type { UserRole } from '@/types/api';

/**
 * 좌측 내비게이션.
 *
 * 표시 여부는 `canAccessPath` 로 정합니다. 권한표(01 문서)와 화면이 갈라지지 않게 같은
 * 함수를 씁니다. 다시 말하지만 이건 노이즈 제거이지 통제가 아닙니다 — 주소를 직접 쳐서
 * 들어가면 페이지가 `/403` 으로 보내고, 조작 자체는 backend 가 막습니다.
 */
const NAV_ITEMS = [
  { href: '/', label: '대시보드', icon: LayoutDashboard },
  { href: '/teams', label: '팀', icon: Users },
  { href: '/users', label: '사용자', icon: UserRound },
  { href: '/keys', label: 'Virtual Key', icon: KeyRound },
  { href: '/models', label: '모델 카탈로그', icon: Boxes },
  { href: '/usage', label: '사용량·비용', icon: ChartColumn },
  { href: '/budgets', label: '예산', icon: Wallet },
  { href: '/rate-limits', label: 'Rate limit', icon: Gauge },
  { href: '/my', label: '내 정보', icon: UserRound },
  { href: '/settings/service-tokens', label: '설정', icon: Settings },
] as const;

export function Sidebar({ role }: { role: UserRole }) {
  const pathname = usePathname();
  const visible = NAV_ITEMS.filter((item) => canAccessPath(item.href, role));

  return (
    <nav className="flex w-56 shrink-0 flex-col gap-0.5 border-r border-border bg-surface px-2.5 py-3">
      <Link href="/" className="mb-3 flex items-center gap-2 px-2 py-1">
        <span className="flex size-7 items-center justify-center rounded-(--radius-base) bg-primary text-primary-foreground">
          <KeyRound className="size-3.5" />
        </span>
        <span className="text-sm font-semibold">llm-gateway</span>
      </Link>

      {visible.map(({ href, label, icon: Icon }) => {
        const active = href === '/' ? pathname === '/' : pathname.startsWith(href.split('/').slice(0, 2).join('/'));
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              'flex items-center gap-2 rounded-(--radius-base) px-2 py-1.5 text-sm transition-colors',
              active
                ? 'bg-primary-soft font-medium text-primary'
                : 'text-muted-foreground hover:bg-surface-muted hover:text-foreground',
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
