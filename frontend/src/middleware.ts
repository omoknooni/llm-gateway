import { NextResponse, type NextRequest } from 'next/server';

import { isPublicPath } from '@/lib/auth/permissions';

/**
 * 인증 게이트 — **쿠키 유무만** 봅니다.
 *
 * 역할 인가는 여기서 하지 않습니다. 우리 backend 는 role 을 토큰 claim 으로 내보내지 않고
 * DB 로 판정하므로, 토큰을 뜯어 역할을 읽으면 화면과 backend 의 판정이 갈립니다.
 * 역할은 콘솔 레이아웃에서 `GET /me` 로 확인합니다(00 문서 Authorization).
 *
 * 미들웨어에서 `GET /me` 를 부르지 않는 이유는 모든 요청에 API 왕복이 붙기 때문입니다.
 */
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api/health).*)'],
};

const SESSION_COOKIE_NAME = 'admin_session';

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // 로그인·로그아웃 라우트 자체는 세션이 없어야 들어옵니다.
  if (pathname.startsWith('/api/auth/') || isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (request.cookies.get(SESSION_COOKIE_NAME)?.value) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = '/login';
  loginUrl.search = '';
  // 로그인 후 원래 가려던 곳으로 돌려보냅니다. 열린 리다이렉트가 되지 않게 경로만 싣습니다.
  if (pathname !== '/') loginUrl.searchParams.set('next', pathname);
  return NextResponse.redirect(loginUrl);
}
