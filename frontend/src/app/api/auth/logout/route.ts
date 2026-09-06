import { NextResponse, type NextRequest } from 'next/server';

import { SESSION_COOKIE_NAME } from '@/lib/api/client';
import { internalRedirectUrl } from '@/lib/auth/redirect';

/**
 * 로그아웃 — 쿠키를 지우는 것이 전부입니다.
 *
 * backend 에 세션 저장소가 없어 서버측 무효화 개념이 없습니다. OIDC 도입 시 IdP 의
 * end-session 엔드포인트로 넘기는 단계가 여기에 붙습니다.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const response = NextResponse.redirect(internalRedirectUrl(request, '/login'), { status: 303 });
  response.cookies.delete(SESSION_COOKIE_NAME);
  return response;
}
