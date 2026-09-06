/**
 * dev 토큰 생성 — 로컬 개발 전용.
 *
 * 형식은 backend `core/auth.py` 의 `_parse_dev_token` 계약입니다:
 *   `dev.<base64url(json payload)>.<sig>`
 * 서명은 검증되지 않습니다. backend 도 `DEV_LOGIN_ENABLED=true` 일 때만 이 경로를 엽니다.
 *
 * **두 설정을 항상 함께 맞춥니다.** 프론트만 켜면 토큰을 굽고도 전부 401 이 납니다.
 */
export interface DevTokenPayload {
  user_id?: string;
  email: string;
  role: string;
  team_id?: string | null;
}

export function buildDevToken(payload: DevTokenPayload): string {
  const encoded = Buffer.from(JSON.stringify(payload), 'utf-8').toString('base64url');
  return `dev.${encoded}.unsigned`;
}
