import 'server-only';

import { cookies } from 'next/headers';

import { AdminApiError, toAdminApiError } from './errors';

/**
 * Admin API 클라이언트 — **서버 전용**입니다.
 *
 * `server-only` import 가 클라이언트 번들에 들어가는 순간 빌드를 실패시킵니다. 세션 토큰이
 * 브라우저로 새는 경로를 컴파일 타임에 막는 장치입니다(00 문서 경계 규칙).
 */

export const SESSION_COOKIE_NAME = 'admin_session';

/** GET 만 재시도합니다. 변경 요청은 멱등하지 않습니다(VK 발급이 중복됩니다). */
const GET_RETRY_ATTEMPTS = 3;
const GET_RETRY_BASE_DELAY_MS = 120;

type QueryValue = string | number | boolean | undefined | null;

function baseUrl(): string {
  const url = process.env.ADMIN_API_URL;
  if (!url) {
    // 조용히 기본값으로 뜨면 모든 화면이 이유 없이 비어 보입니다.
    throw new AdminApiError(
      500,
      'config_error',
      'ADMIN_API_URL 이 설정되지 않았습니다',
      {},
      '',
    );
  }
  return url.replace(/\/$/, '');
}

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function sessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(SESSION_COOKIE_NAME)?.value;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await sessionToken();
  const url = `${baseUrl()}${path}`;

  const init: RequestInit = {
    method,
    // 정책 콘솔에서 오래된 값을 보여주는 것은 버그입니다(00 문서 Data Fetching).
    cache: 'no-store',
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };

  const attempts = method === 'GET' ? GET_RETRY_ATTEMPTS : 1;
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(url, init);
    } catch {
      // 연결 실패 원인(DNS/타임아웃)은 서버 로그에만 남기고 화면에는 노출하지 않습니다.
      lastError = new AdminApiError(
        503,
        'admin_api_unreachable',
        'Admin API 에 연결할 수 없습니다',
        { url },
        '',
      );
      if (attempt < attempts) {
        await delay(GET_RETRY_BASE_DELAY_MS * attempt);
        continue;
      }
      throw lastError;
    }

    const requestId = response.headers.get('x-request-id') ?? '';

    if (response.ok) {
      if (response.status === 204) return undefined as T;
      return (await parseBody(response)) as T;
    }

    const error = toAdminApiError(response.status, await parseBody(response), requestId);

    // 5xx 만 재시도합니다. 4xx 는 다시 보내도 같은 답이 옵니다.
    if (attempt < attempts && response.status >= 500) {
      lastError = error;
      await delay(GET_RETRY_BASE_DELAY_MS * attempt);
      continue;
    }
    throw error;
  }

  throw lastError ?? new AdminApiError(500, 'internal_error', '요청을 완료하지 못했습니다');
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const adminApi = {
  get: <T>(path: string, params?: Record<string, QueryValue>) =>
    request<T>('GET', `${path}${buildQuery(params)}`),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  delete: <T>(path: string, params?: Record<string, QueryValue>) =>
    request<T>('DELETE', `${path}${buildQuery(params)}`),
};

export { AdminApiError };
