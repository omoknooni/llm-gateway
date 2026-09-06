import { UserRole } from '@/types/api';

/**
 * 페이지 권한표. 01 문서의 표와 1:1 로 대응합니다.
 *
 * **표에 없는 경로는 기본 거부**입니다. 새 화면을 만들면서 여기에 등록하지 않으면 아무도
 * 들어갈 수 없고, 그게 반대(모두 통과)보다 안전합니다.
 *
 * 이 표는 화면 노이즈를 줄이는 장치이지 통제가 아닙니다. 실제 통제는 backend 의 403 입니다.
 */
export const PAGE_PERMISSIONS: Record<string, readonly UserRole[]> = {
  '/': [UserRole.ADMIN, UserRole.TEAM_LEADER],
  '/teams': [UserRole.ADMIN, UserRole.TEAM_LEADER],
  '/users': [UserRole.ADMIN, UserRole.TEAM_LEADER],
  '/keys': [UserRole.ADMIN, UserRole.TEAM_LEADER],
  '/models': [UserRole.ADMIN, UserRole.TEAM_LEADER],
  // ADMIN 을 넣지 않습니다. 플랫폼 운영자가 "내 사용량"을 보면 역할 경계가 흐려집니다.
  '/my': [UserRole.TEAM_LEADER, UserRole.MEMBER],
  '/settings': [UserRole.ADMIN],
};

/** 로그인 없이 열리는 경로. `/403` 이 빠지면 리다이렉트가 자기 자신을 물어 무한 루프가 됩니다. */
export const PUBLIC_PATHS = ['/login', '/403'] as const;

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

/**
 * 경로 접근 가능 여부. 가장 구체적인(긴) prefix 가 이깁니다.
 *
 * `/`는 정확히 일치할 때만 매칭합니다. prefix 규칙을 그대로 적용하면 모든 경로를 삼켜
 * 하위 항목이 영영 평가되지 않습니다.
 */
export function canAccessPath(pathname: string, role: UserRole): boolean {
  const match = Object.entries(PAGE_PERMISSIONS)
    .filter(([prefix]) =>
      prefix === '/' ? pathname === '/' : pathname === prefix || pathname.startsWith(`${prefix}/`),
    )
    .sort(([a], [b]) => b.length - a.length)[0];

  if (!match) return false;
  return match[1].includes(role);
}

/** 응답의 role 문자열을 우리 enum 으로 좁힙니다. 모르는 값은 가장 낮은 권한으로 봅니다. */
export function toUserRole(raw: string): UserRole {
  return raw === UserRole.ADMIN || raw === UserRole.TEAM_LEADER || raw === UserRole.MEMBER
    ? raw
    : UserRole.MEMBER;
}
