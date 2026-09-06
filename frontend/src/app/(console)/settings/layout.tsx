import Link from 'next/link';

import { PageHeader } from '@/components/ui/card';

const TABS = [
  { href: '/settings/service-tokens', label: '서비스 토큰' },
  { href: '/settings/cache', label: '캐시' },
] as const;

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader
        title="설정"
        description="플랫폼 운영자 전용. 자격 증명과 캐시 정합성을 다룹니다."
      />
      <nav className="mb-4 flex gap-1 border-b border-border">
        {TABS.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:border-border hover:text-foreground"
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      {children}
    </>
  );
}
