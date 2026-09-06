import 'server-only';

import { cache } from 'react';

import type { MeResponse } from '@/types/api';

import { adminApi } from './client';

/**
 * 현재 주체. **역할의 원천은 이 응답입니다**(00 문서 Authorization).
 *
 * `cache()`로 요청 단위 중복 호출을 제거합니다. 레이아웃과 페이지가 각각 불러도 왕복은 한 번입니다.
 */
export const getMe = cache(async (): Promise<MeResponse> => adminApi.get<MeResponse>('/api/v1/me'));
