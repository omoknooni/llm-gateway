import 'server-only';

import type {
  Page,
  TeamCreateRequest,
  TeamLeaderRequest,
  TeamResponse,
  TeamRevokeAllRequest,
  TeamRevokeAllResponse,
  TeamUpdateRequest,
  UserResponse,
} from '@/types/api';

import { adminApi } from './client';

export interface TeamListQuery {
  is_active?: boolean;
  cursor?: string;
  limit?: number;
}

export const listTeams = (query: TeamListQuery = {}) =>
  adminApi.get<Page<TeamResponse>>('/api/v1/teams', { ...query });

export const getTeam = (teamId: string) =>
  adminApi.get<TeamResponse>(`/api/v1/teams/${teamId}`);

export const listTeamMembers = (teamId: string) =>
  adminApi.get<UserResponse[]>(`/api/v1/teams/${teamId}/members`);

export const createTeam = (body: TeamCreateRequest) =>
  adminApi.post<TeamResponse>('/api/v1/teams', body);

export const updateTeam = (teamId: string, body: TeamUpdateRequest) =>
  adminApi.patch<TeamResponse>(`/api/v1/teams/${teamId}`, body);

export const setTeamLeader = (teamId: string, body: TeamLeaderRequest) =>
  adminApi.put<TeamResponse>(`/api/v1/teams/${teamId}/leader`, body);

/** 되돌릴 수 없는 조작입니다. `confirm_team_name`이 팀 이름과 정확히 같아야 합니다. */
export const revokeAllTeamKeys = (teamId: string, body: TeamRevokeAllRequest) =>
  adminApi.post<TeamRevokeAllResponse>(`/api/v1/teams/${teamId}/virtual-keys/revoke-all`, body);
