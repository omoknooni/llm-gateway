import Link from 'next/link';
import { ShieldX } from 'lucide-react';

export const metadata = { title: '권한 없음 — llm-gateway Admin' };

export default function ForbiddenPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-md text-center">
        <ShieldX className="mx-auto size-8 text-danger" />
        <h1 className="mt-3 text-lg font-semibold">이 화면에 접근할 권한이 없습니다</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          역할에 허용되지 않은 경로입니다. 권한이 필요하다면 플랫폼 관리자에게 요청하세요.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block text-sm text-primary underline-offset-4 hover:underline"
        >
          대시보드로 돌아가기
        </Link>
      </div>
    </main>
  );
}
