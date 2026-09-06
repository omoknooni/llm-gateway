import type { ErrorEnvelope } from '@/types/api';

/**
 * Admin API 실패를 하나의 타입으로 모읍니다.
 *
 * 화면은 HTTP 상태가 아니라 `code`로 분기합니다. `code`는 backend 가 계약으로 고정한
 * 안정 식별자이고, 상태 코드는 같은 409 안에 여러 원인이 섞입니다(backend 00 문서).
 */
export class AdminApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId: string = '',
  ) {
    super(message);
    this.name = 'AdminApiError';
  }

  /** 인증 만료. 화면은 로그인으로 보냅니다. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** 권한 경계. backend 는 다른 팀 리소스에 404 가 아니라 403 을 줍니다. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

/** 응답 본문을 에러 봉투로 해석합니다. 봉투가 아니면(502 HTML 등) 폴백합니다. */
export function toAdminApiError(status: number, body: unknown, fallbackRequestId = ''): AdminApiError {
  if (isErrorEnvelope(body)) {
    const { code, message, details, request_id } = body.error;
    return new AdminApiError(status, code, message, details ?? {}, request_id || fallbackRequestId);
  }

  // FastAPI 의 요청 검증 실패(422)는 우리 봉투를 거치지 않고 detail 배열로 옵니다.
  if (status === 422 && isFastApiValidationBody(body)) {
    return new AdminApiError(
      422,
      'validation_error',
      '입력값이 올바르지 않습니다',
      { fieldErrors: toFieldErrors(body.detail) },
      fallbackRequestId,
    );
  }

  return new AdminApiError(
    status,
    status >= 500 ? 'internal_error' : 'unknown_error',
    `Admin API 요청이 실패했습니다 (HTTP ${status})`,
    {},
    fallbackRequestId,
  );
}

/** 422 상세를 `필드명 → 메시지`로 풀어 폼에 붙일 수 있게 만듭니다. */
export function fieldErrorsOf(error: AdminApiError): Record<string, string> | undefined {
  const raw = error.details['fieldErrors'];
  return isStringRecord(raw) ? raw : undefined;
}

interface FastApiValidationBody {
  detail: { loc: unknown[]; msg: string }[];
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false;
  const error = (body as { error: unknown }).error;
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
  );
}

function isFastApiValidationBody(body: unknown): body is FastApiValidationBody {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return false;
  const detail = (body as { detail: unknown }).detail;
  return Array.isArray(detail);
}

function toFieldErrors(detail: { loc: unknown[]; msg: string }[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const item of detail) {
    if (!Array.isArray(item?.loc) || typeof item?.msg !== 'string') continue;
    // loc 는 ["body", "field", ...] 형태입니다. 앞의 위치 표시를 떼고 필드명만 씁니다.
    const path = item.loc.filter((part): part is string => typeof part === 'string');
    const field = path[path.length - 1];
    if (field && field !== 'body' && !(field in result)) {
      result[field] = item.msg;
    }
  }
  return result;
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === 'object' &&
    value !== null &&
    Object.values(value).every((item) => typeof item === 'string')
  );
}
