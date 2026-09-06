import 'server-only';

import type {
  ModelCreateRequest,
  ModelResponse,
  ModelStatus,
  ModelStatusRequest,
  ModelUpdateRequest,
  PricingCreateRequest,
  PricingResponse,
} from '@/types/api';

import { adminApi } from './client';

export const listModels = (status?: ModelStatus) =>
  adminApi.get<ModelResponse[]>('/api/v1/models', { status });

export const getModel = (alias: string) =>
  adminApi.get<ModelResponse>(`/api/v1/models/${alias}`);

/** 단가 없는 모델은 사용량이 비용으로 환산되지 않습니다. 대시보드가 이 목록을 봅니다. */
export const listModelsMissingPricing = () =>
  adminApi.get<string[]>('/api/v1/models/missing-pricing');

export const createModel = (body: ModelCreateRequest) =>
  adminApi.post<ModelResponse>('/api/v1/models', body);

export const updateModel = (alias: string, body: ModelUpdateRequest) =>
  adminApi.patch<ModelResponse>(`/api/v1/models/${alias}`, body);

export const setModelStatus = (alias: string, body: ModelStatusRequest) =>
  adminApi.patch<ModelResponse>(`/api/v1/models/${alias}/status`, body);

export const listPricings = (alias: string) =>
  adminApi.get<PricingResponse[]>(`/api/v1/models/${alias}/pricings`);

/** 구간이 겹치면 backend 가 409 로 막습니다. 화면은 그 메시지를 그대로 보여줍니다. */
export const createPricing = (alias: string, body: PricingCreateRequest) =>
  adminApi.post<PricingResponse>(`/api/v1/models/${alias}/pricings`, body);
