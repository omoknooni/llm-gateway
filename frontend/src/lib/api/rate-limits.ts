import 'server-only';

import type {
  EffectiveLimitsResponse,
  RateLimitListResponse,
  RateLimitScope,
  RateLimitSetRequest,
  RateLimitSetResponse,
  RateLimitTreeResponse,
  RateLimitUsageResponse,
} from '@/types/api';

import { adminApi } from './client';

/**
 * rate limit 설정·해석(backend M8).
 *
 * 경로에 scope 가 박혀 있습니다 — 같은 `PUT` 이라도 scope 마다 권한과 계층 제약이 다릅니다.
 * `model_alias` 를 생략하면 그 scope 의 **모든 모델**에 적용됩니다.
 */

export const setGlobalLimit = (modelAlias: string, body: RateLimitSetRequest) =>
  adminApi.put<RateLimitSetResponse>(`/api/v1/rate-limits/global/${modelAlias}`, body);

export const setTeamLimit = (teamId: string, body: RateLimitSetRequest, modelAlias?: string) =>
  adminApi.put<RateLimitSetResponse>(
    `/api/v1/rate-limits/team/${teamId}${modelAlias ? `?model_alias=${encodeURIComponent(modelAlias)}` : ''}`,
    body,
  );

export const setUserLimit = (userId: string, body: RateLimitSetRequest, modelAlias?: string) =>
  adminApi.put<RateLimitSetResponse>(
    `/api/v1/rate-limits/user/${userId}${modelAlias ? `?model_alias=${encodeURIComponent(modelAlias)}` : ''}`,
    body,
  );

export const setVirtualKeyLimit = (keyId: string, body: RateLimitSetRequest, modelAlias?: string) =>
  adminApi.put<RateLimitSetResponse>(
    `/api/v1/rate-limits/virtual-key/${keyId}${modelAlias ? `?model_alias=${encodeURIComponent(modelAlias)}` : ''}`,
    body,
  );

/** `GLOBAL` 은 대상이 없으므로 `scope_id` 자리에 `global` 을 씁니다. */
export const deleteRateLimit = (scope: RateLimitScope, scopeId: string, modelAlias?: string) =>
  adminApi.delete<void>(`/api/v1/rate-limits/${scope}/${scopeId}`, { model_alias: modelAlias });

export const listRateLimits = (
  query: { scope?: RateLimitScope; scope_id?: string; model_alias?: string } = {},
) => adminApi.get<RateLimitListResponse>('/api/v1/rate-limits', { ...query });

/** 대상을 지정하지 않으면 **자기 자신**의 해석 결과입니다. */
export const getEffectiveLimits = (
  query: { user_id?: string; virtual_key_id?: string; model_alias?: string } = {},
) => adminApi.get<EffectiveLimitsResponse>('/api/v1/rate-limits/effective', { ...query });

export const getRateLimitTree = (teamId: string, modelAlias?: string) =>
  adminApi.get<RateLimitTreeResponse>('/api/v1/rate-limits/tree', {
    team_id: teamId,
    model_alias: modelAlias,
  });

/** best-effort. `available=false` 여도 설정 화면은 계속 동작해야 합니다. */
export const getRateLimitUsage = (
  query: { scope?: RateLimitScope; scope_id?: string; model_alias?: string } = {},
) => adminApi.get<RateLimitUsageResponse>('/api/v1/rate-limits/usage', { ...query });
