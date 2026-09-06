import 'server-only';

import { redirect } from 'next/navigation';

import { getMe } from '@/lib/api/me';
import { AdminApiError } from '@/lib/api/errors';
import { UserRole } from '@/types/api';

import { canAccessPath, toUserRole } from './permissions';

export interface AdminSession {
  userId: string;
  email: string;
  role: UserRole;
  teamId: string | null;
  isServiceToken: boolean;
}

/**
 * 현재 세션. **역할은 `GET /me`가 원천이고 토큰 payload 가 아닙니다**(00 문서).
 *
 * 401 이면 쿠키가 죽었다는 뜻이므로 로그인으로 보냅니다. 그 외 오류는 삼키지 않고 던져서
 * 에러 경계가 원인을 보여주게 합니다 — Admin API 가 죽은 것을 "로그아웃"으로 위장하면
 * 운영자가 잘못된 곳을 찾아 헤맵니다.
 */
export async function requireSession(): Promise<AdminSession> {
  try {
    const me = await getMe();
    return {
      userId: me.user_id,
      email: me.email,
      role: toUserRole(me.role),
      teamId: me.team_id,
      isServiceToken: me.is_service_token,
    };
  } catch (error) {
    if (error instanceof AdminApiError && error.isUnauthenticated) {
      redirect('/login');
    }
    throw error;
  }
}

/** 세션을 확인하고 경로 권한까지 검사합니다. 권한이 없으면 `/403`. */
export async function requirePageAccess(pathname: string): Promise<AdminSession> {
  const session = await requireSession();
  if (!canAccessPath(pathname, session.role)) {
    redirect('/403');
  }
  return session;
}
