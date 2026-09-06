import { AdminApiError, fieldErrorsOf } from '@/lib/api/errors';

/**
 * Server Action 결과 봉투.
 *
 * 예외를 그대로 던지지 않는 이유는 Next 가 프로덕션 빌드에서 서버 예외 메시지를 지우기
 * 때문입니다. 그러면 사용자에게 "오류가 발생했습니다" 밖에 남지 않고, backend 가 애써 만든
 * `code` 와 `request_id` 가 화면에 도달하지 못합니다(00 문서 Error Contract).
 */
export type ActionResult<T = void> =
  | { ok: true; data: T }
  | { ok: false; code: string; message: string; requestId?: string; fieldErrors?: Record<string, string> };

export function actionOk<T>(data: T): ActionResult<T> {
  return { ok: true, data };
}

/** 알 수 없는 예외를 결과 봉투로 바꿉니다. 내부 예외 타입을 화면에 노출하지 않습니다. */
export function actionFailure(error: unknown): ActionResult<never> {
  if (error instanceof AdminApiError) {
    return {
      ok: false,
      code: error.code,
      message: error.message,
      requestId: error.requestId,
      fieldErrors: fieldErrorsOf(error),
    };
  }
  return {
    ok: false,
    code: 'unknown_error',
    message: error instanceof Error ? error.message : '알 수 없는 오류가 발생했습니다',
  };
}

/** 폼 필드 검증 실패를 backend 왕복 없이 돌려줍니다. */
export function actionFieldErrors(fieldErrors: Record<string, string>): ActionResult<never> {
  return {
    ok: false,
    code: 'validation_error',
    message: '입력값을 확인해 주세요',
    fieldErrors,
  };
}
