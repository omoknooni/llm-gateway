'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import {
  issueVirtualKey,
  revokeVirtualKey,
  rotateVirtualKey,
  updateVirtualKey,
} from '@/lib/api/virtual-keys';
import type {
  RevokeReason,
  VKOwnerType,
  VirtualKeyCreateResponse,
  VirtualKeyResponse,
} from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

const issueSchema = z.object({
  name: z.string().trim().min(1, '키 이름을 입력하세요').max(100, '이름이 너무 깁니다'),
  owner_id: z.string().trim().min(1, '소유자를 선택하세요'),
  expires_at: z.string().trim().min(1, '만료 시각을 지정하세요'),
});

/**
 * Virtual Key 발급.
 *
 * 응답의 `virtual_key` 원문은 이 반환값이 유일한 전달 경로입니다. 화면은 이 값을
 * 다이얼로그에 한 번 보여주고 상태에서 지웁니다. 로그·토스트·URL 에 싣지 않습니다.
 */
export async function issueVirtualKeyAction(input: {
  name: string;
  owner_type: VKOwnerType;
  owner_id: string;
  expires_at: string;
  allowed_model_aliases: string[];
}): Promise<ActionResult<VirtualKeyCreateResponse>> {
  const parsed = issueSchema.safeParse(input);
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const key = issue.path[0];
      if (typeof key === 'string' && !(key in fieldErrors)) fieldErrors[key] = issue.message;
    }
    return actionFieldErrors(fieldErrors);
  }

  try {
    const key = await issueVirtualKey({
      name: parsed.data.name,
      owner_type: input.owner_type,
      owner_id: parsed.data.owner_id,
      expires_at: parsed.data.expires_at,
      // 빈 배열은 "축소하지 않음"입니다. 값이 있을 때만 실어 보냅니다.
      ...(input.allowed_model_aliases.length
        ? { allowed_model_aliases: input.allowed_model_aliases }
        : {}),
    });
    revalidatePath('/keys');
    return actionOk(key);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function updateVirtualKeyAction(
  keyId: string,
  input: { name?: string; expires_at?: string; allowed_model_aliases?: string[] },
): Promise<ActionResult<VirtualKeyResponse>> {
  try {
    const key = await updateVirtualKey(keyId, {
      ...(input.name === undefined ? {} : { name: input.name.trim() }),
      ...(input.expires_at === undefined ? {} : { expires_at: input.expires_at }),
      ...(input.allowed_model_aliases === undefined
        ? {}
        : { allowed_model_aliases: input.allowed_model_aliases }),
    });
    revalidatePath('/keys');
    revalidatePath(`/keys/${keyId}`);
    return actionOk(key);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 로테이션. 새 키를 발급하고 이전 키를 유예 기간 뒤에 끊습니다.
 *
 * 유예 동안 **두 키가 모두 통합니다.** 그게 무중단 교체의 요점이고, 동시에 위험이기도 해서
 * 화면은 유예 시간을 명시적으로 입력받습니다.
 */
export async function rotateVirtualKeyAction(
  keyId: string,
  input: { gracePeriodHours: number; reason: string },
): Promise<ActionResult<VirtualKeyCreateResponse>> {
  if (!Number.isInteger(input.gracePeriodHours) || input.gracePeriodHours < 0) {
    return actionFieldErrors({ grace_period_hours: '0 이상의 정수를 입력하세요' });
  }

  try {
    const key = await rotateVirtualKey(keyId, {
      grace_period_hours: input.gracePeriodHours,
      reason: input.reason.trim() || null,
    });
    revalidatePath('/keys');
    revalidatePath(`/keys/${keyId}`);
    return actionOk(key);
  } catch (error) {
    return actionFailure(error);
  }
}

/** 폐기. 사유는 감사 요구사항이라 생략할 수 없습니다. */
export async function revokeVirtualKeyAction(
  keyId: string,
  input: { reason: RevokeReason; note: string },
): Promise<ActionResult<void>> {
  try {
    await revokeVirtualKey(keyId, input.reason, input.note.trim() || undefined);
    revalidatePath('/keys');
    revalidatePath(`/keys/${keyId}`);
    revalidatePath('/my');
    return actionOk(undefined);
  } catch (error) {
    return actionFailure(error);
  }
}
