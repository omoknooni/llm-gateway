/**
 * 커서 페이지네이션의 URL 계산.
 *
 * backend 는 offset 을 주지 않으므로 페이지 번호가 없습니다. "이전"은 방문한 커서를
 * `stack` 에 쌓아 되돌아가는 방식입니다. 상태를 URL 에 두면 새로고침·링크 공유에서 같은
 * 화면이 나옵니다(00 문서 Data Fetching).
 *
 * 컴포넌트에서 분리한 이유는 이 규칙이 테스트로 고정되어야 하기 때문입니다 —
 * `has_more=false` 일 때 다음이 죽는 것, 첫 페이지에서 이전이 죽는 것.
 */
export const CURSOR_PARAM = 'cursor';
export const STACK_PARAM = 'stack';
const STACK_SEPARATOR = '~';

export interface PaginationHrefs {
  previous: string | null;
  next: string | null;
}

export function buildPaginationHrefs(
  pathname: string,
  searchParams: URLSearchParams,
  page: { nextCursor: string | null; hasMore: boolean },
): PaginationHrefs {
  const currentCursor = searchParams.get(CURSOR_PARAM);
  const stack = (searchParams.get(STACK_PARAM) ?? '').split(STACK_SEPARATOR).filter(Boolean);

  const href = (params: Record<string, string | null>): string => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(params)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    const query = next.toString();
    return query ? `${pathname}?${query}` : pathname;
  };

  // 첫 페이지에는 돌아갈 곳이 없습니다.
  const previous = currentCursor
    ? href({
        [CURSOR_PARAM]: stack[stack.length - 1] ?? null,
        [STACK_PARAM]: stack.length > 1 ? stack.slice(0, -1).join(STACK_SEPARATOR) : null,
      })
    : null;

  // `has_more=false` 면 다음 커서가 와도 따라가지 않습니다. 마지막 페이지입니다.
  const nextStack = [...stack, currentCursor].filter((item): item is string => Boolean(item));
  const next =
    page.hasMore && page.nextCursor
      ? href({
          [CURSOR_PARAM]: page.nextCursor,
          // 첫 페이지에서는 쌓을 커서가 없습니다. 빈 `stack=` 을 URL 에 남기지 않습니다.
          [STACK_PARAM]: nextStack.length ? nextStack.join(STACK_SEPARATOR) : null,
        })
      : null;

  return { previous, next };
}
