import { describe, expect, it } from 'vitest';

import { buildPaginationHrefs } from '@/lib/cursor';

const hrefs = (query: string, page: { nextCursor: string | null; hasMore: boolean }) =>
  buildPaginationHrefs('/keys', new URLSearchParams(query), page);

describe('buildPaginationHrefs', () => {
  it('마지막 페이지에서는 다음이 죽는다', () => {
    expect(hrefs('', { nextCursor: 'c1', hasMore: false }).next).toBeNull();
    expect(hrefs('', { nextCursor: null, hasMore: true }).next).toBeNull();
  });

  it('첫 페이지에서는 이전이 죽는다', () => {
    expect(hrefs('status=ACTIVE', { nextCursor: 'c1', hasMore: true }).previous).toBeNull();
  });

  it('다음으로 이동하면 현재 커서가 스택에 쌓인다', () => {
    const first = hrefs('', { nextCursor: 'c1', hasMore: true });
    expect(first.next).toBe('/keys?cursor=c1');

    const second = hrefs('cursor=c1', { nextCursor: 'c2', hasMore: true });
    expect(second.next).toBe('/keys?cursor=c2&stack=c1');
  });

  it('이전으로 돌아가면 스택에서 하나를 꺼낸다', () => {
    const page3 = hrefs('cursor=c2&stack=c1', { nextCursor: 'c3', hasMore: true });
    expect(page3.previous).toBe('/keys?cursor=c1');
  });

  it('필터는 페이지를 옮겨도 유지된다', () => {
    const result = hrefs('status=ACTIVE&q=prod', { nextCursor: 'c1', hasMore: true });
    expect(result.next).toContain('status=ACTIVE');
    expect(result.next).toContain('q=prod');
  });
});
