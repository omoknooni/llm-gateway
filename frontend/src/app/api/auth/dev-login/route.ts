import { NextResponse, type NextRequest } from 'next/server';

import { SESSION_COOKIE_NAME } from '@/lib/api/client';
import { buildDevToken } from '@/lib/auth/dev-token';
import { internalRedirectUrl, isSecureRequest } from '@/lib/auth/redirect';
import { UserRole } from '@/types/api';

/**
 * dev 로그인 — `DEV_LOGIN_ENABLED=true` 일 때만 열립니다.
 *
 * backend 도 같은 이름의 설정으로 같은 경로를 열고 닫습니다. **두 값을 항상 함께 맞춥니다.**
 * 프론트만 켜면 토큰을 굽고도 모든 API 가 401 을 냅니다.
 */
const MAX_AGE_SECONDS = 60 * 60 * 12;

const ALLOWED_ROLES: string[] = [UserRole.ADMIN, UserRole.TEAM_LEADER, UserRole.MEMBER];

function enabled(): boolean {
  return process.env.DEV_LOGIN_ENABLED === 'true';
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!enabled()) {
    return new NextResponse(null, { status: 404 });
  }

  const form = await request.formData();
  const role = String(form.get('role') ?? '');
  const email = String(form.get('email') ?? '').trim() || 'admin@dev.local';
  const teamId = String(form.get('team_id') ?? '').trim();
  const next = String(form.get('next') ?? '/');

  if (!ALLOWED_ROLES.includes(role)) {
    return NextResponse.json(
      { error: { code: 'validation_error', message: '알 수 없는 역할입니다' } },
      { status: 400 },
    );
  }

  const token = buildDevToken({
    // 비우면 backend 가 합성 주체(DEV_ACTOR_ID)를 씁니다. 실제 사용자로 들어가려면
    // DEV_LOGIN_USER_ID 에 auth.users 의 UUID 를 넣습니다.
    ...(process.env.DEV_LOGIN_USER_ID ? { user_id: process.env.DEV_LOGIN_USER_ID } : {}),
    email,
    role,
    team_id: teamId || null,
  });

  const response = NextResponse.redirect(internalRedirectUrl(request, next), { status: 303 });
  response.cookies.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    maxAge: MAX_AGE_SECONDS,
    // HTTP 로 접속한 로컬에서 secure 를 켜면 브라우저가 쿠키를 버려 로그인 루프가 됩니다.
    secure: process.env.SESSION_COOKIE_SECURE === 'true' || isSecureRequest(request),
  });
  return response;
}
