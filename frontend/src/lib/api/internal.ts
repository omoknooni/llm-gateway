import 'server-only';

import { adminApi } from './client';

/**
 * 미해결 캐시 무효화 재시도.
 *
 * control plane 은 캐시를 **삭제만** 합니다. 값을 채우는 주체는 gateway 입니다(AGENTS.md).
 * 이 호출은 실패해서 쌓인 삭제 작업을 다시 시도할 뿐, 값을 쓰지 않습니다.
 */
export const retryCacheInvalidation = () =>
  adminApi.post<Record<string, number>>('/api/v1/internal/cache/retry');
