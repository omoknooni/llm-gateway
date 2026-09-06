import type { NextRequest } from 'next/server';

/**
 * Route Handler 에서 쓸 절대 URL을 요청 헤더로 만듭니다.
 *
 * `request.nextUrl` 을 쓰지 않는 이유: Route Handler 안에서는 nextUrl 의 host 가 서버 자신의
 * 호스트(`localhost:PORT`)로 정규화되어 실제 Host 헤더를 잃습니다(미들웨어는 유지합니다).
 * 그대로 리다이렉트하면 ALB 뒤에서 사용자가 localhost 로 튕깁니다.
 *
 * `pathname` 은 내부 절대경로만 허용합니다. 외부 URL 로 새어 나가는 열린 리다이렉트를 막습니다.
 */
export function internalRedirectUrl(request: NextRequest, pathname: string): URL {
  const forwardedHost = request.headers.get('x-forwarded-host');
  const host = forwardedHost ?? request.headers.get('host') ?? request.nextUrl.host;
  const proto =
    request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim() ??
    request.nextUrl.protocol.replace(':', '');

  const safe = pathname.startsWith('/') && !pathname.startsWith('//') ? pathname : '/';
  return new URL(safe, `${proto}://${host}`);
}

/** 요청이 HTTPS 로 들어왔는지. 세션 쿠키의 Secure 플래그를 정할 때 씁니다. */
export function isSecureRequest(request: NextRequest): boolean {
  const proto =
    request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim() ??
    request.nextUrl.protocol.replace(':', '');
  return proto === 'https';
}
