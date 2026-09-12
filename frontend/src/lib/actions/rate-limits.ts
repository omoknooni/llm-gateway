'use server';

import { revalidatePath } from 'next/cache';

import {
  deleteRateLimit,
  setGlobalLimit,
  setTeamLimit,
  setUserLimit,
  setVirtualKeyLimit,
} from '@/lib/api/rate-limits';
import {
  LIMIT_FIELDS,
  RateLimitScope,
  type RateLimitSetRequest,
  type RateLimitSetResponse,
} from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

/**
 * 입력 문자열 → 한도 값.
 *
 * 빈 칸은 `null` 이고 **"이 층에서 정의하지 않음"** 입니다(상위로 폴백). 행을 지우는 것과
 * 다르므로 삭제는 별도 버튼입니다. `0` 은 backend 가 거절합니다 — 전면 차단이 필요하면
 * 키를 폐기하는 것이 맞습니다(backend 06 문서).
 */
function parseLimit(raw: string): number | null | 'invalid' {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (!/^\d+$/.test(trimmed)) return 'invalid';
  const value = Number(trimmed);
  return value > 0 ? value : 'invalid';
}

export async function setRateLimitAction(
  target: { scope: RateLimitScope; scopeId: string | null; modelAlias?: string },
  input: { rpm_limit: string; tpm_limit: string; concurrency_limit: string },
): Promise<ActionResult<RateLimitSetResponse>> {
  const errors: Record<string, string> = {};
  const body: RateLimitSetRequest = {};

  for (const field of LIMIT_FIELDS) {
    const parsed = parseLimit(input[field]);
    if (parsed === 'invalid') {
      errors[field] = '1 이상의 정수를 입력하거나 비워 두세요';
    } else {
      body[field] = parsed;
    }
  }
  if (Object.keys(errors).length > 0) return actionFieldErrors(errors);
  if (LIMIT_FIELDS.every((field) => body[field] === null)) {
    return actionFieldErrors({
      rpm_limit: '하나 이상을 입력하세요. 정의를 지우려면 해제 버튼을 쓰세요',
    });
  }

  const { scope, scopeId, modelAlias } = target;
  try {
    let result: RateLimitSetResponse;
    if (scope === RateLimitScope.GLOBAL) {
      if (!modelAlias) return actionFieldErrors({ model_alias: '전역 한도는 모델을 지정해야 합니다' });
      result = await setGlobalLimit(modelAlias, body);
    } else if (!scopeId) {
      return actionFieldErrors({ scope_id: '대상을 지정하세요' });
    } else if (scope === RateLimitScope.TEAM) {
      result = await setTeamLimit(scopeId, body, modelAlias);
    } else if (scope === RateLimitScope.USER) {
      result = await setUserLimit(scopeId, body, modelAlias);
    } else {
      result = await setVirtualKeyLimit(scopeId, body, modelAlias);
    }
    revalidatePath('/rate-limits');
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}

/** 정의 전체 제거. `null` 저장과 다릅니다 — 이 층이 사라지고 상위로 폴백합니다. */
export async function deleteRateLimitAction(
  scope: RateLimitScope,
  scopeId: string | null,
  modelAlias?: string,
): Promise<ActionResult<void>> {
  try {
    // GLOBAL 은 대상이 없어 경로 자리표시자로 `global` 을 씁니다(backend 06 문서).
    await deleteRateLimit(scope, scope === RateLimitScope.GLOBAL ? 'global' : (scopeId ?? ''), modelAlias);
    revalidatePath('/rate-limits');
    return actionOk(undefined);
  } catch (error) {
    return actionFailure(error);
  }
}
