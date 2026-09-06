import type { Metadata } from 'next';

import { ToastProvider } from '@/components/ui/toast';
import { THEME_INIT_SCRIPT } from '@/components/ui/theme-toggle';

import './globals.css';

export const metadata: Metadata = {
  title: 'llm-gateway Admin',
  description: '사내 LLM Gateway 관리 콘솔 — 팀·사용자·Virtual Key·모델 카탈로그',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        {/* 첫 페인트 전에 테마를 적용해 라이트 → 다크 깜빡임을 없앱니다. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
