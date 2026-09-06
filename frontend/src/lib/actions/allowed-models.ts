'use server';

import { revalidatePath } from 'next/cache';

import {
  clearUserAllowedModels,
  setTeamAllowedModels,
  setUserAllowedModels,
} from '@/lib/api/allowed-models';
import type { AllowedModelsResponse } from '@/types/api';

import { actionFailure, actionOk, type ActionResult } from './types';

export async function setTeamAllowedModelsAction(
  teamId: string,
  aliases: string[],
): Promise<ActionResult<AllowedModelsResponse>> {
  try {
    const result = await setTeamAllowedModels(teamId, { model_aliases: aliases });
    revalidatePath(`/teams/${teamId}`);
    // 팀 정책이 바뀌면 소속 사용자의 실효 모델도 달라집니다.
    revalidatePath('/users');
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function setUserAllowedModelsAction(
  userId: string,
  aliases: string[],
): Promise<ActionResult<AllowedModelsResponse>> {
  try {
    const result = await setUserAllowedModels(userId, { model_aliases: aliases });
    revalidatePath(`/users/${userId}`);
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 개인 층 자체를 걷어냅니다.
 *
 * 빈 배열 저장(`아무 것도 선택하지 않고 저장`)과 다릅니다. 빈 배열은 "이 사용자는 어떤
 * 모델도 쓸 수 없음"이고, 해제는 "개인 설정을 지워 팀 또는 카탈로그가 이기게 함"입니다.
 * 두 조작을 버튼으로 분리해 둔 이유가 이것입니다(backend 04 문서 3층 해석).
 */
export async function clearUserAllowedModelsAction(
  userId: string,
): Promise<ActionResult<AllowedModelsResponse>> {
  try {
    const result = await clearUserAllowedModels(userId);
    revalidatePath(`/users/${userId}`);
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}
