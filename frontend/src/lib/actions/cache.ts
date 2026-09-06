'use server';

import { retryCacheInvalidation } from '@/lib/api/internal';

import { actionFailure, actionOk, type ActionResult } from './types';

/**
 * 미해결 캐시 무효화 재시도.
 *
 * 무효화는 best-effort 입니다. Redis 오류로 삭제에 실패해도 업무 트랜잭션은 이미 커밋된
 * 상태라 롤백하지 않고 `audit.cache_invalidation_failures` 에 남습니다(backend 00 문서).
 * 이 조작은 그 잔량을 다시 지우는 것뿐이고, 캐시에 값을 쓰지 않습니다.
 */
export async function retryCacheInvalidationAction(): Promise<
  ActionResult<Record<string, number>>
> {
  try {
    return actionOk(await retryCacheInvalidation());
  } catch (error) {
    return actionFailure(error);
  }
}
