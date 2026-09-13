import 'server-only';

import type {
  AuthEventSummaryResponse,
  LeaderboardResponse,
  TrendGranularity,
  UsageAxis,
  UsageMetric,
  UsageOverviewResponse,
  UsageTrendResponse,
} from '@/types/api';

import { adminApi } from './client';

/**
 * 사용량·비용 조회(backend M7).
 *
 * 네 엔드포인트가 **같은 필터 집합**을 받습니다. drill-down 은 별도 경로가 아니라 같은
 * 엔드포인트에 필터를 더하는 것입니다(backend 10 문서).
 *
 * 인가 범위 축소는 backend 가 합니다. 팀장이 다른 팀을 지정하면 빈 결과가 아니라 403 이고,
 * 화면은 그 구분을 지우지 않습니다.
 */
export interface UsageQuery {
  from_date?: string;
  to_date?: string;
  team_id?: string;
  user_id?: string;
  virtual_key_id?: string;
  model_alias?: string;
}

export const getUsageOverview = (query: UsageQuery = {}) =>
  adminApi.get<UsageOverviewResponse>('/api/v1/usage/overview', { ...query });

export const getUsageLeaderboard = (
  query: UsageQuery & { axis?: UsageAxis; metric?: UsageMetric; limit?: number } = {},
) => adminApi.get<LeaderboardResponse>('/api/v1/usage/leaderboard', { ...query });

export const getUsageTrend = (query: UsageQuery & { granularity?: TrendGranularity } = {}) =>
  adminApi.get<UsageTrendResponse>('/api/v1/usage/trend', { ...query });

/** 정책 거절(401/403/429). 실제 실패 수는 `occurrence_count` 입니다. */
export const getAuthEventSummary = (query: UsageQuery = {}) =>
  adminApi.get<AuthEventSummaryResponse>('/api/v1/usage/auth-events', { ...query });
