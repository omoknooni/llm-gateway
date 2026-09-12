import { describe, expect, it } from 'vitest';

import { canAccessPath, isPublicPath, toUserRole } from '@/lib/auth/permissions';
import { UserRole } from '@/types/api';

describe('canAccessPath', () => {
  it('표에 없는 경로는 기본 거부한다', () => {
    // 아직 화면이 없는 경로들입니다. 새 화면을 만들면서 권한표에 등록하지 않으면 아무도
    // 못 들어가고, 그게 반대(모두 통과)보다 안전합니다.
    expect(canAccessPath('/audit-logs', UserRole.ADMIN)).toBe(false);
    expect(canAccessPath('/whatever', UserRole.ADMIN)).toBe(false);
  });

  it('관측·정책 화면(F6)은 ADMIN·팀장에게만 열린다', () => {
    for (const path of ['/usage', '/budgets', '/budgets/team/abc', '/rate-limits']) {
      expect(canAccessPath(path, UserRole.ADMIN)).toBe(true);
      expect(canAccessPath(path, UserRole.TEAM_LEADER)).toBe(true);
      // MEMBER 가 보는 화면은 `/my` 하나입니다. 자기 예산은 거기에 있습니다.
      expect(canAccessPath(path, UserRole.MEMBER)).toBe(false);
    }
  });

  it("루트는 정확히 '/' 일 때만 매칭해 하위 경로를 삼키지 않는다", () => {
    // '/' 가 prefix 로 매칭되면 /settings 가 TEAM_LEADER 에게도 열립니다.
    expect(canAccessPath('/settings/service-tokens', UserRole.TEAM_LEADER)).toBe(false);
    expect(canAccessPath('/settings/service-tokens', UserRole.ADMIN)).toBe(true);
  });

  it('가장 구체적인 prefix 가 이긴다', () => {
    expect(canAccessPath('/users/tree', UserRole.TEAM_LEADER)).toBe(true);
    expect(canAccessPath('/my', UserRole.ADMIN)).toBe(false);
    expect(canAccessPath('/my', UserRole.MEMBER)).toBe(true);
  });

  it('MEMBER 는 관리 화면에 들어가지 못한다', () => {
    for (const path of ['/', '/teams', '/users', '/keys', '/models']) {
      expect(canAccessPath(path, UserRole.MEMBER)).toBe(false);
    }
  });
});

describe('isPublicPath', () => {
  it('403 이 공개여야 리다이렉트 루프가 생기지 않는다', () => {
    expect(isPublicPath('/403')).toBe(true);
    expect(isPublicPath('/login')).toBe(true);
    expect(isPublicPath('/keys')).toBe(false);
  });
});

describe('toUserRole', () => {
  it('모르는 역할 문자열은 가장 낮은 권한으로 좁힌다', () => {
    expect(toUserRole('SUPERUSER')).toBe(UserRole.MEMBER);
    expect(toUserRole('ADMIN')).toBe(UserRole.ADMIN);
  });
});
