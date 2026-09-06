import { describe, expect, it } from 'vitest';

import { AdminApiError, fieldErrorsOf, toAdminApiError } from '@/lib/api/errors';

describe('toAdminApiError', () => {
  it('backend 의 에러 봉투를 code·message·request_id 로 푼다', () => {
    const error = toAdminApiError(409, {
      error: {
        code: 'duplicate_alias',
        message: '이미 존재하는 alias 입니다',
        details: { alias: 'claude-sonnet-4' },
        request_id: '0f9c',
      },
    });

    expect(error).toBeInstanceOf(AdminApiError);
    expect(error.code).toBe('duplicate_alias');
    expect(error.message).toBe('이미 존재하는 alias 입니다');
    expect(error.details['alias']).toBe('claude-sonnet-4');
    expect(error.requestId).toBe('0f9c');
  });

  it('봉투가 아닌 응답(프록시 HTML 등)에도 죽지 않고 폴백한다', () => {
    const error = toAdminApiError(502, '<html>Bad Gateway</html>', 'req-1');
    expect(error.code).toBe('internal_error');
    expect(error.status).toBe(502);
    expect(error.requestId).toBe('req-1');
  });

  it('봉투가 없으면 헤더의 request_id 라도 살린다', () => {
    expect(toAdminApiError(400, undefined, 'req-2').requestId).toBe('req-2');
  });

  it('FastAPI 422 를 필드 단위 오류로 푼다', () => {
    const error = toAdminApiError(422, {
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address' },
        { loc: ['body', 'display_name'], msg: 'Field required' },
      ],
    });

    expect(error.code).toBe('validation_error');
    expect(fieldErrorsOf(error)).toEqual({
      email: 'value is not a valid email address',
      display_name: 'Field required',
    });
  });

  it('상태별 분기 헬퍼가 backend 규약과 맞는다', () => {
    // 다른 팀 리소스는 404 가 아니라 403 입니다(backend 00 문서).
    expect(toAdminApiError(403, { error: { code: 'forbidden', message: '' } }).isForbidden).toBe(
      true,
    );
    expect(
      toAdminApiError(401, { error: { code: 'unauthenticated', message: '' } }).isUnauthenticated,
    ).toBe(true);
  });
});
