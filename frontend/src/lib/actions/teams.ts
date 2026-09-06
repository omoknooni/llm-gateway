'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import {
  createTeam,
  revokeAllTeamKeys,
  setTeamLeader,
  updateTeam,
} from '@/lib/api/teams';
import { RevokeReason, type TeamResponse, type TeamRevokeAllResponse } from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

const teamNameSchema = z
  .string()
  .trim()
  .min(1, '팀 이름을 입력하세요')
  .max(100, '팀 이름은 100자 이하여야 합니다');

export async function createTeamAction(input: {
  name: string;
  description: string;
}): Promise<ActionResult<TeamResponse>> {
  const parsed = teamNameSchema.safeParse(input.name);
  if (!parsed.success) {
    return actionFieldErrors({ name: parsed.error.issues[0]?.message ?? '이름이 올바르지 않습니다' });
  }

  try {
    const team = await createTeam({
      name: parsed.data,
      description: input.description.trim() || null,
    });
    revalidatePath('/teams');
    return actionOk(team);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function updateTeamAction(
  teamId: string,
  input: { name?: string; description?: string; is_active?: boolean },
): Promise<ActionResult<TeamResponse>> {
  if (input.name !== undefined) {
    const parsed = teamNameSchema.safeParse(input.name);
    if (!parsed.success) {
      return actionFieldErrors({
        name: parsed.error.issues[0]?.message ?? '이름이 올바르지 않습니다',
      });
    }
  }

  try {
    const team = await updateTeam(teamId, {
      ...(input.name === undefined ? {} : { name: input.name.trim() }),
      ...(input.description === undefined ? {} : { description: input.description.trim() || null }),
      ...(input.is_active === undefined ? {} : { is_active: input.is_active }),
    });
    revalidatePath('/teams');
    revalidatePath(`/teams/${teamId}`);
    return actionOk(team);
  } catch (error) {
    return actionFailure(error);
  }
}

/** `userId: null` 이면 팀장 해제입니다. */
export async function setTeamLeaderAction(
  teamId: string,
  userId: string | null,
): Promise<ActionResult<TeamResponse>> {
  try {
    const team = await setTeamLeader(teamId, { user_id: userId });
    revalidatePath(`/teams/${teamId}`);
    revalidatePath('/users');
    return actionOk(team);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 팀 소유 VK 일괄 폐기. 되돌릴 수 없습니다.
 *
 * `confirm_team_name` 검증은 backend 도 하지만 여기서 먼저 막습니다. 잘못된 팀 이름으로
 * 서버까지 갔다가 409 를 받는 것보다, 입력 시점에 걸리는 편이 낫습니다.
 */
export async function revokeAllTeamKeysAction(
  teamId: string,
  input: { confirmTeamName: string; reason: RevokeReason },
): Promise<ActionResult<TeamRevokeAllResponse>> {
  if (!input.confirmTeamName.trim()) {
    return actionFieldErrors({ confirm_team_name: '팀 이름을 입력하세요' });
  }

  try {
    const result = await revokeAllTeamKeys(teamId, {
      confirm_team_name: input.confirmTeamName.trim(),
      reason: input.reason ?? RevokeReason.INCIDENT,
    });
    revalidatePath(`/teams/${teamId}`);
    revalidatePath('/keys');
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}
