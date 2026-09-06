import 'server-only';

import type {
  Page,
  RevokeReason,
  VKOwnerType,
  VKStatus,
  VirtualKeyAuditResponse,
  VirtualKeyCreateRequest,
  VirtualKeyCreateResponse,
  VirtualKeyResponse,
  VirtualKeyRotateRequest,
  VirtualKeyUpdateRequest,
} from '@/types/api';

import { adminApi } from './client';

export interface VirtualKeyListQuery {
  owner_type?: VKOwnerType;
  owner_id?: string;
  team_id?: string;
  status?: VKStatus;
  /** 이 시각 이전에 만료되는 키. 만료 임박 조회에 씁니다. */
  expires_before?: string;
  /** 이 시각 이후로 쓰인 적 없는 키. 유휴 키 정리에 씁니다. */
  unused_since?: string;
  q?: string;
  cursor?: string;
  limit?: number;
}

export const listVirtualKeys = (query: VirtualKeyListQuery = {}) =>
  adminApi.get<Page<VirtualKeyResponse>>('/api/v1/virtual-keys', { ...query });

export const getVirtualKey = (keyId: string) =>
  adminApi.get<VirtualKeyResponse>(`/api/v1/virtual-keys/${keyId}`);

export const getVirtualKeyAudit = (keyId: string) =>
  adminApi.get<VirtualKeyAuditResponse>(`/api/v1/virtual-keys/${keyId}/audit`);

/** 응답의 `virtual_key` 원문은 재조회 경로가 없습니다. 화면에서 한 번만 보여줍니다. */
export const issueVirtualKey = (body: VirtualKeyCreateRequest) =>
  adminApi.post<VirtualKeyCreateResponse>('/api/v1/virtual-keys', body);

export const updateVirtualKey = (keyId: string, body: VirtualKeyUpdateRequest) =>
  adminApi.patch<VirtualKeyResponse>(`/api/v1/virtual-keys/${keyId}`, body);

export const rotateVirtualKey = (keyId: string, body: VirtualKeyRotateRequest) =>
  adminApi.post<VirtualKeyCreateResponse>(`/api/v1/virtual-keys/${keyId}/rotate`, body);

/** 사유는 감사 요구사항이라 생략할 수 없습니다(backend 03 문서). */
export const revokeVirtualKey = (keyId: string, reason: RevokeReason, note?: string) =>
  adminApi.delete<void>(`/api/v1/virtual-keys/${keyId}`, { reason, note });
