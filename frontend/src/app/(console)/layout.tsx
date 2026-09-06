import { Header } from '@/components/layout/header';
import { Sidebar } from '@/components/layout/sidebar';
import { requireSession } from '@/lib/auth/session';

/**
 * 콘솔 셸.
 *
 * 여기서 `GET /me` 를 한 번 호출하고, 하위 페이지는 `cache()` 덕분에 왕복 없이 같은 세션을
 * 재사용합니다. 경로별 역할 검사는 각 페이지가 `requirePageAccess` 로 수행합니다 —
 * 레이아웃은 자신이 어떤 경로에 있는지 알 수 없기 때문입니다.
 */
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const session = await requireSession();

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar role={session.role} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header session={session} />
        <main className="flex-1 overflow-auto px-6 py-5">{children}</main>
      </div>
    </div>
  );
}
