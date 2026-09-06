'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import { issueServiceToken, revokeServiceToken, rotateServiceToken } from '@/lib/api/service-tokens';
import type { ServiceTokenCreateResponse } from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

const schema = z.object({
  name: z.string().trim().min(1, '토큰 이름을 입력하세요').max(100, '이름이 너무 깁니다'),
  expires_in_days: z
    .number()
    .int('정수를 입력하세요')
    .min(1, '1일 이상이어야 합니다')
    .max(365, '365일을 넘을 수 없습니다'),
});

/**
 * 서비스 토큰 발급.
 *
 * 검증되면 ADMIN 권한의 합성 주체가 됩니다. 사람 계정과 같은 권한을 갖는 자격 증명이므로
 * 원문 취급은 Virtual Key 와 동일합니다 — 한 번만 보여주고 재조회 경로를 만들지 않습니다.
 */
export async function issueServiceTokenAction(input: {
  name: string;
  expiresInDays: number;
}): Promise<ActionResult<ServiceTokenCreateResponse>> {
  const parsed = schema.safeParse({ name: input.name, expires_in_days: input.expiresInDays });
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const key = issue.path[0];
      if (typeof key === 'string' && !(key in fieldErrors)) fieldErrors[key] = issue.message;
    }
    return actionFieldErrors(fieldErrors);
  }

  try {
    const token = await issueServiceToken({
      name: parsed.data.name,
      expires_in_days: parsed.data.expires_in_days,
    });
    revalidatePath('/settings/service-tokens');
    return actionOk(token);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function rotateServiceTokenAction(
  tokenId: string,
  input: { name: string; expiresInDays: number },
): Promise<ActionResult<ServiceTokenCreateResponse>> {
  try {
    const token = await rotateServiceToken(tokenId, {
      name: input.name.trim(),
      expires_in_days: input.expiresInDays,
    });
    revalidatePath('/settings/service-tokens');
    return actionOk(token);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function revokeServiceTokenAction(tokenId: string): Promise<ActionResult<void>> {
  try {
    await revokeServiceToken(tokenId);
    revalidatePath('/settings/service-tokens');
    return actionOk(undefined);
  } catch (error) {
    return actionFailure(error);
  }
}
