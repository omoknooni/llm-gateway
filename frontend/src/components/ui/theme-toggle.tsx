'use client';

import { Moon, Sun } from 'lucide-react';
import { useEffect, useState } from 'react';

const STORAGE_KEY = 'llm-gateway-admin-theme';

/**
 * 라이트/다크 전환.
 *
 * 라이브러리를 쓰지 않고 `<html class="dark">` 만 토글합니다. 초기값은 레이아웃의 인라인
 * 스크립트가 정하므로 여기서는 첫 페인트 이후에만 개입합니다(깜빡임 방지).
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains('dark'));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? 'dark' : 'light');
    } catch {
      // 저장이 막혀도(프라이빗 모드 등) 이번 세션 전환은 동작합니다.
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? '라이트 모드로 전환' : '다크 모드로 전환'}
      className="inline-flex size-8 items-center justify-center rounded-(--radius-base) text-muted-foreground hover:bg-surface-muted hover:text-foreground"
    >
      {dark ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

/** 첫 페인트 전에 테마를 적용하는 인라인 스크립트. 흰 화면 깜빡임을 없앱니다. */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('${STORAGE_KEY}');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (stored === 'dark' || (!stored && prefersDark)) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) {}
})();
`;
