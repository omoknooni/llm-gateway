import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';

import { internalRedirectUrl, isSecureRequest } from '@/lib/auth/redirect';

function requestWith(headers: Record<string, string>): NextRequest {
  return new NextRequest('http://localhost:3000/api/auth/dev-login', { headers });
}

describe('internalRedirectUrl', () => {
  it('실제 Host 헤더를 유지한다', () => {
    // Route Handler 의 nextUrl 은 host 를 서버 자신으로 정규화합니다. 그대로 쓰면
    // ALB 뒤에서 사용자가 localhost 로 튕깁니다.
    const url = internalRedirectUrl(requestWith({ host: 'admin.internal.example.com' }), '/keys');
    expect(url.toString()).toBe('http://admin.internal.example.com/keys');
  });

  it('프록시 헤더가 있으면 그쪽을 우선한다', () => {
    const url = internalRedirectUrl(
      requestWith({
        host: '10.0.1.5:3000',
        'x-forwarded-host': 'admin.example.com',
        'x-forwarded-proto': 'https',
      }),
      '/',
    );
    expect(url.toString()).toBe('https://admin.example.com/');
  });

  it('쉼표로 이어진 x-forwarded-proto 에서 첫 값만 쓴다', () => {
    expect(isSecureRequest(requestWith({ 'x-forwarded-proto': 'https, http' }))).toBe(true);
    expect(isSecureRequest(requestWith({ host: 'localhost:3000' }))).toBe(false);
  });

  it('외부 URL 로 새는 열린 리다이렉트를 막는다', () => {
    const request = requestWith({ host: 'admin.example.com' });
    expect(internalRedirectUrl(request, 'https://evil.example.com/steal').host).toBe(
      'admin.example.com',
    );
    expect(internalRedirectUrl(request, '//evil.example.com/steal').host).toBe(
      'admin.example.com',
    );
  });

  it('경로에 붙은 쿼리를 유지한다', () => {
    const url = internalRedirectUrl(requestWith({ host: 'a.example.com' }), '/keys?status=ACTIVE');
    expect(url.pathname).toBe('/keys');
    expect(url.search).toBe('?status=ACTIVE');
  });
});
