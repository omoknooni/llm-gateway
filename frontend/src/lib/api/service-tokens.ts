import 'server-only';

import type {
  ServiceTokenCreateRequest,
  ServiceTokenCreateResponse,
  ServiceTokenResponse,
} from '@/types/api';

import { adminApi } from './client';

export const listServiceTokens = (includeRevoked = false) =>
  adminApi.get<ServiceTokenResponse[]>('/api/v1/service-tokens', {
    include_revoked: includeRevoked,
  });

/** 원문은 VK 와 같은 규칙입니다 — 한 번만 보여주고 재조회 경로를 만들지 않습니다. */
export const issueServiceToken = (body: ServiceTokenCreateRequest) =>
  adminApi.post<ServiceTokenCreateResponse>('/api/v1/service-tokens', body);

export const rotateServiceToken = (tokenId: string, body: ServiceTokenCreateRequest) =>
  adminApi.post<ServiceTokenCreateResponse>(`/api/v1/service-tokens/${tokenId}/rotate`, body);

export const revokeServiceToken = (tokenId: string) =>
  adminApi.delete<void>(`/api/v1/service-tokens/${tokenId}`);
