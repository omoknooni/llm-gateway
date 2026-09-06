'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import { createUser, deactivateUser, transferUserTeam, updateUser } from '@/lib/api/users';
import type {
  UserDeactivateResponse,
  UserResponse,
  UserRole,
  UserTransferResponse,
} from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

const createSchema = z.object({
  email: z.string().trim().email('올바른 이메일 형식이 아닙니다'),
  display_name: z.string().trim().min(1, '표시명을 입력하세요').max(100, '표시명이 너무 깁니다'),
});

export async function createUserAction(input: {
  email: string;
  display_name: string;
  role: UserRole;
  team_id: string;
}): Promise<ActionResult<UserResponse>> {
  const parsed = createSchema.safeParse(input);
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const key = issue.path[0];
      if (typeof key === 'string' && !(key in fieldErrors)) fieldErrors[key] = issue.message;
    }
    return actionFieldErrors(fieldErrors);
  }

  try {
    const user = await createUser({
      email: parsed.data.email,
      display_name: parsed.data.display_name,
      role: input.role,
      team_id: input.team_id || null,
    });
    revalidatePath('/users');
    return actionOk(user);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function updateUserAction(
  userId: string,
  input: { display_name?: string; role?: UserRole; is_active?: boolean },
): Promise<ActionResult<UserResponse>> {
  try {
    const user = await updateUser(userId, {
      ...(input.display_name === undefined ? {} : { display_name: input.display_name.trim() }),
      ...(input.role === undefined ? {} : { role: input.role }),
      ...(input.is_active === undefined ? {} : { is_active: input.is_active }),
    });
    revalidatePath('/users');
    revalidatePath(`/users/${userId}`);
    return actionOk(user);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 사용자 비활성화.
 *
 * 소유 VK 가 함께 폐기되고 캐시가 무효화됩니다. 응답의 파급 결과를 그대로 돌려주어
 * 화면이 "몇 개가 폐기됐고 캐시가 반영됐는지"를 보여줄 수 있게 합니다(01 문서).
 */
export async function deactivateUserAction(
  userId: string,
): Promise<ActionResult<UserDeactivateResponse>> {
  try {
    const result = await deactivateUser(userId);
    revalidatePath('/users');
    revalidatePath(`/users/${userId}`);
    revalidatePath('/keys');
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}

/** `teamId: null` 이면 팀에서 빼냅니다. 소유 VK 의 인증 캐시가 함께 지워집니다. */
export async function transferUserTeamAction(
  userId: string,
  input: { teamId: string | null; reason: string },
): Promise<ActionResult<UserTransferResponse>> {
  try {
    const result = await transferUserTeam(userId, {
      team_id: input.teamId,
      reason: input.reason.trim() || null,
    });
    revalidatePath('/users');
    revalidatePath(`/users/${userId}`);
    revalidatePath('/teams');
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}
