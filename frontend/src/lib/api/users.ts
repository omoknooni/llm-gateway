import 'server-only';

import type {
  OrgTreeTeam,
  Page,
  UserCreateRequest,
  UserDeactivateResponse,
  UserResponse,
  UserRole,
  UserTeamTransferRequest,
  UserTransferResponse,
  UserUpdateRequest,
} from '@/types/api';

import { adminApi } from './client';

export interface UserListQuery {
  team_id?: string;
  role?: UserRole;
  is_active?: boolean;
  q?: string;
  cursor?: string;
  limit?: number;
}

export const listUsers = (query: UserListQuery = {}) =>
  adminApi.get<Page<UserResponse>>('/api/v1/users', { ...query });

export const getUser = (userId: string) =>
  adminApi.get<UserResponse>(`/api/v1/users/${userId}`);

export const getOrgTree = () => adminApi.get<OrgTreeTeam[]>('/api/v1/users/tree');

export const createUser = (body: UserCreateRequest) =>
  adminApi.post<UserResponse>('/api/v1/users', body);

export const updateUser = (userId: string, body: UserUpdateRequest) =>
  adminApi.patch<UserResponse>(`/api/v1/users/${userId}`, body);

/** 응답의 `revoked_virtual_keys`·`cache_invalidated`를 화면에 그대로 보여줍니다. */
export const deactivateUser = (userId: string) =>
  adminApi.post<UserDeactivateResponse>(`/api/v1/users/${userId}/deactivate`);

export const transferUserTeam = (userId: string, body: UserTeamTransferRequest) =>
  adminApi.put<UserTransferResponse>(`/api/v1/users/${userId}/team`, body);
