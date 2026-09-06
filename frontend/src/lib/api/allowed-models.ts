import 'server-only';

import type {
  AllowedModelsRequest,
  AllowedModelsResponse,
  EffectiveModelsResponse,
} from '@/types/api';

import { adminApi } from './client';

export const getTeamAllowedModels = (teamId: string) =>
  adminApi.get<AllowedModelsResponse>(`/api/v1/teams/${teamId}/allowed-models`);

export const setTeamAllowedModels = (teamId: string, body: AllowedModelsRequest) =>
  adminApi.put<AllowedModelsResponse>(`/api/v1/teams/${teamId}/allowed-models`, body);

export const getUserAllowedModels = (userId: string) =>
  adminApi.get<AllowedModelsResponse>(`/api/v1/users/${userId}/allowed-models`);

export const setUserAllowedModels = (userId: string, body: AllowedModelsRequest) =>
  adminApi.put<AllowedModelsResponse>(`/api/v1/users/${userId}/allowed-models`, body);

/**
 * 개인 설정 자체를 걷어냅니다.
 *
 * 빈 배열 설정(`PUT {model_aliases: []}`)과 의미가 다릅니다. 빈 배열은 "아무 모델도 허용하지
 * 않음"이고, 해제는 "개인 층을 비워 상위 층이 이기게 함"입니다(backend 04 문서 3층 해석).
 */
export const clearUserAllowedModels = (userId: string) =>
  adminApi.delete<AllowedModelsResponse>(`/api/v1/users/${userId}/allowed-models`);

export const getEffectiveModels = (userId: string) =>
  adminApi.get<EffectiveModelsResponse>(`/api/v1/users/${userId}/effective-models`);
