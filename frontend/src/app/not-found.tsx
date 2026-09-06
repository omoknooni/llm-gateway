import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <div className="max-w-md text-center">
        <h1 className="text-lg font-semibold">페이지를 찾을 수 없습니다</h1>
        <p className="mt-2 text-sm text-muted-foreground">주소가 바뀌었거나 삭제된 화면입니다.</p>
        <Link href="/" className="mt-4 inline-block text-sm text-primary underline-offset-4 hover:underline">
          대시보드로 돌아가기
        </Link>
      </div>
    </main>
  );
}
