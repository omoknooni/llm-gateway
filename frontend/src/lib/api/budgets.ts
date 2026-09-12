import 'server-only';

import type {
  AllocationResponse,
  AllocationSetRequest,
  BudgetConfigResponse,
  BudgetScope,
  BudgetSetRequest,
  BudgetSummaryResponse,
  MyBudgetResponse,
  ReseedRequest,
  ReseedResponse,
  TeamBudgetUsageResponse,
  UnsetBudgetResponse,
} from '@/types/api';

import { adminApi } from './client';

/**
 * 예산 조회·설정(backend M6).
 *
 * `period` 는 `YYYY-MM` 이고 **경계는 UTC** 입니다. 화면 표시는 KST 지만 기간 경계까지 KST 로
 * 옮기면 gateway 집행 카운터와 다른 월을 보게 됩니다(backend 05 문서).
 *
 * 사용자 예산은 팀 배분(`PUT .../allocation`)으로만 다룹니다. backend 에 사용자 단건 설정
 * API 도 있지만, 화면 경로가 둘이면 합계 검증을 어느 쪽이 했는지 흐려집니다. 단건 경로가
 * 필요해지면 그때 감쌉니다.
 */

export const setTeamBudget = (teamId: string, body: BudgetSetRequest) =>
  adminApi.put<BudgetConfigResponse>(`/api/v1/budgets/team/${teamId}`, body);

/** 해제는 **무제한**입니다. 0 으로 설정하는 것과 다릅니다. */
export const clearTeamBudget = (teamId: string) =>
  adminApi.delete<void>(`/api/v1/budgets/team/${teamId}`);

export const getAllocation = (teamId: string, period?: string) =>
  adminApi.get<AllocationResponse>(`/api/v1/budgets/team/${teamId}/allocation`, { period });

/** **전체 교체**입니다. 합계가 팀 한도를 넘으면 409 로 전체가 거절됩니다. */
export const setAllocation = (teamId: string, body: AllocationSetRequest) =>
  adminApi.put<AllocationResponse>(`/api/v1/budgets/team/${teamId}/allocation`, body);

export const getBudgetSummary = (query: { scope?: BudgetScope; period?: string } = {}) =>
  adminApi.get<BudgetSummaryResponse>('/api/v1/budgets/summary', { ...query });

/** 미설정 = 무제한이라 상시 노출이 유일한 방어선입니다(ADMIN 전용). */
export const listUnsetBudgets = (teamId?: string) =>
  adminApi.get<UnsetBudgetResponse>('/api/v1/budgets/unset', { team_id: teamId });

export const getTeamBudgetUsage = (teamId: string, period?: string) =>
  adminApi.get<TeamBudgetUsageResponse>(`/api/v1/budgets/team/${teamId}/usage`, { period });

export const getMyBudget = (period?: string) =>
  adminApi.get<MyBudgetResponse>('/api/v1/me/budget', { period });

/** 운영 예외. ADMIN 전용이고 감사에 before/after 가 남습니다. */
export const reseedBudgetUsage = (body: ReseedRequest) =>
  adminApi.put<ReseedResponse>('/api/v1/budgets/usages/reseed', body);
