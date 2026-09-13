'use server';

import { revalidatePath } from 'next/cache';

import {
  clearTeamBudget,
  reseedBudgetUsage,
  setAllocation,
  setTeamBudget,
} from '@/lib/api/budgets';
import {
  BudgetPolicy,
  BudgetScope,
  type AllocationResponse,
  type BudgetConfigResponse,
  type ReseedResponse,
} from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

/**
 * 금액은 문자열입니다. `Number()` 로 파싱하지 않고 **형식과 자릿수만** 검사합니다.
 *
 * 소수 4자리는 backend 의 `numeric(14,4)` 와 같은 제약입니다. 여기서 걸러 두면 표현할 수 없는
 * 값이 DB 와 집행 카운터에서 다르게 반올림되는 것을 왕복 없이 막습니다(backend 05 문서).
 */
const MONEY_PATTERN = /^\d{1,10}(\.\d{1,4})?$/;

function validateMoney(value: string, field: string): Record<string, string> {
  return MONEY_PATTERN.test(value.trim())
    ? {}
    : { [field]: '0 이상, 소수점 4자리까지의 숫자로 입력하세요' };
}

export async function setTeamBudgetAction(
  teamId: string,
  input: { limit_usd: string; policy: BudgetPolicy; warn_thresholds?: number[] },
): Promise<ActionResult<BudgetConfigResponse>> {
  const errors = validateMoney(input.limit_usd, 'limit_usd');
  if (Object.keys(errors).length > 0) return actionFieldErrors(errors);

  try {
    const config = await setTeamBudget(teamId, {
      limit_usd: input.limit_usd.trim(),
      policy: input.policy,
      ...(input.warn_thresholds ? { warn_thresholds: input.warn_thresholds } : {}),
    });
    revalidatePath('/budgets');
    revalidatePath(`/budgets/team/${teamId}`);
    return actionOk(config);
  } catch (error) {
    return actionFailure(error);
  }
}

/** 해제는 **무제한**입니다. 0 설정과 다르므로 화면도 다른 문구를 씁니다. */
export async function clearTeamBudgetAction(teamId: string): Promise<ActionResult<void>> {
  try {
    await clearTeamBudget(teamId);
    revalidatePath('/budgets');
    revalidatePath(`/budgets/team/${teamId}`);
    return actionOk(undefined);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 배분 저장. **전체 교체**입니다 — 보내지 않은 멤버의 배분은 해제됩니다.
 *
 * 합계가 팀 한도를 넘으면 backend 가 409 `allocation_exceeds_team_budget` 으로 전체를
 * 거절합니다. 화면에서 미리 더해 보여주되, 판정은 backend 것을 그대로 씁니다.
 */
export async function setAllocationAction(
  teamId: string,
  input: { allocations: { user_id: string; limit_usd: string }[]; policy: BudgetPolicy },
): Promise<ActionResult<AllocationResponse>> {
  const errors: Record<string, string> = {};
  for (const item of input.allocations) {
    Object.assign(errors, validateMoney(item.limit_usd, `limit_usd:${item.user_id}`));
  }
  if (Object.keys(errors).length > 0) return actionFieldErrors(errors);

  try {
    const allocation = await setAllocation(teamId, {
      allocations: input.allocations.map((item) => ({
        user_id: item.user_id,
        limit_usd: item.limit_usd.trim(),
      })),
      policy: input.policy,
    });
    revalidatePath(`/budgets/team/${teamId}`);
    revalidatePath('/budgets');
    return actionOk(allocation);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 소진값 재시드. **운영 예외**입니다(backend 05 문서).
 *
 * control plane 이 집행 카운터를 쓰는 유일한 경로라 사유가 필수이고, 실패 시 전체가
 * 취소됩니다. 화면도 일반 저장 버튼처럼 보이지 않게 다룹니다.
 */
export async function reseedBudgetUsageAction(input: {
  scope: BudgetScope;
  scope_id: string;
  period: string;
  used_usd: string;
  reason: string;
}): Promise<ActionResult<ReseedResponse>> {
  const errors = validateMoney(input.used_usd, 'used_usd');
  if (!input.reason.trim()) errors['reason'] = '사유는 감사에 남습니다. 반드시 입력하세요';
  if (Object.keys(errors).length > 0) return actionFieldErrors(errors);

  try {
    const result = await reseedBudgetUsage({
      items: [
        {
          scope: input.scope,
          scope_id: input.scope_id,
          period: input.period,
          used_usd: input.used_usd.trim(),
        },
      ],
      reason: input.reason.trim(),
    });
    revalidatePath('/budgets');
    if (input.scope === BudgetScope.TEAM) revalidatePath(`/budgets/team/${input.scope_id}`);
    return actionOk(result);
  } catch (error) {
    return actionFailure(error);
  }
}
