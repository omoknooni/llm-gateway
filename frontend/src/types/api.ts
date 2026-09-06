/**
 * Admin API 계약 타입.
 *
 * 원천은 `backend/`가 생성하는 OpenAPI 문서입니다. **이름을 backend 스키마와 동일하게
 * 유지합니다.** 프론트에서 이름을 바꾸면 응답과 화면 타입을 대조할 수 없게 됩니다.
 *
 * 금액은 backend가 문자열로 직렬화합니다. 여기서도 `string`이며 `number`로 바꾸지 않습니다.
 * 시간은 ISO-8601 UTC 문자열입니다.
 */

// ── enums ─────────────────────────────────────────────────────────────────────

export const UserRole = {
  ADMIN: 'ADMIN',
  TEAM_LEADER: 'TEAM_LEADER',
  MEMBER: 'MEMBER',
} as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

export const VKStatus = {
  ACTIVE: 'ACTIVE',
  ROTATED: 'ROTATED',
  REVOKED: 'REVOKED',
  EXPIRED: 'EXPIRED',
} as const;
export type VKStatus = (typeof VKStatus)[keyof typeof VKStatus];

export const VKOwnerType = {
  TEAM: 'TEAM',
  USER: 'USER',
} as const;
export type VKOwnerType = (typeof VKOwnerType)[keyof typeof VKOwnerType];

export const RevokeReason = {
  LOST: 'LOST',
  OFFBOARDING: 'OFFBOARDING',
  POLICY_VIOLATION: 'POLICY_VIOLATION',
  INCIDENT: 'INCIDENT',
  ROTATION: 'ROTATION',
  OTHER: 'OTHER',
} as const;
export type RevokeReason = (typeof RevokeReason)[keyof typeof RevokeReason];

export const ModelStatus = {
  ACTIVE: 'ACTIVE',
  INACTIVE: 'INACTIVE',
} as const;
export type ModelStatus = (typeof ModelStatus)[keyof typeof ModelStatus];

export const ApiDialect = {
  OPENAI_CHAT: 'OPENAI_CHAT',
  ANTHROPIC_MESSAGES: 'ANTHROPIC_MESSAGES',
} as const;
export type ApiDialect = (typeof ApiDialect)[keyof typeof ApiDialect];

export const Provider = { BEDROCK: 'BEDROCK' } as const;
export type Provider = (typeof Provider)[keyof typeof Provider];

export const ResolvedFrom = {
  USER: 'USER',
  TEAM: 'TEAM',
  CATALOG: 'CATALOG',
} as const;
export type ResolvedFrom = (typeof ResolvedFrom)[keyof typeof ResolvedFrom];

// ── 공통 봉투 ─────────────────────────────────────────────────────────────────

/** 커서 페이지네이션. offset 은 쓰지 않습니다(backend 00 문서 API Conventions). */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

/** 실패 응답 봉투. 화면은 `code`로 분기하고 `message`를 보여줍니다. */
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

// ── 인증 ──────────────────────────────────────────────────────────────────────

export interface MeResponse {
  user_id: string;
  email: string;
  /** backend 는 이 필드를 문자열로 내지만 값 집합은 UserRole 과 같습니다. */
  role: string;
  team_id: string | null;
  is_service_token: boolean;
}

// ── 팀 ────────────────────────────────────────────────────────────────────────

export interface TeamResponse {
  id: string;
  name: string;
  description: string | null;
  leader_user_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TeamCreateRequest {
  name: string;
  description?: string | null;
}

export interface TeamUpdateRequest {
  name?: string | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface TeamLeaderRequest {
  user_id: string | null;
}

export interface TeamRevokeAllRequest {
  confirm_team_name: string;
  reason?: RevokeReason;
}

export interface TeamRevokeAllResponse {
  team_id: string;
  revoked_virtual_keys: number;
  cache_invalidated: boolean;
}

// ── 사용자 ────────────────────────────────────────────────────────────────────

export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  team_id: string | null;
  provider: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserCreateRequest {
  email: string;
  display_name: string;
  role?: UserRole;
  team_id?: string | null;
}

export interface UserUpdateRequest {
  display_name?: string | null;
  role?: UserRole | null;
  is_active?: boolean | null;
}

export interface UserTeamTransferRequest {
  team_id: string | null;
  reason?: string | null;
}

/** 파급 결과. `cache_invalidated=false`면 정책 반영이 지연된 상태입니다. */
export interface UserTransferResponse {
  user_id: string;
  team_id: string | null;
  previous_team_id: string | null;
  affected_virtual_keys: number;
  cache_invalidated: boolean;
}

export interface UserDeactivateResponse {
  user_id: string;
  revoked_virtual_keys: number;
  cache_invalidated: boolean;
}

export interface OrgTreeMember {
  id: string;
  display_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface OrgTreeTeam {
  id: string;
  name: string;
  is_active: boolean;
  leader_user_id: string | null;
  members: OrgTreeMember[];
}

// ── Virtual Key ───────────────────────────────────────────────────────────────

export interface VirtualKeyResponse {
  id: string;
  name: string;
  key_prefix: string;
  owner_type: VKOwnerType;
  owner_id: string;
  team_id: string;
  status: VKStatus;
  expires_at: string | null;
  last_used_at: string | null;
  rotated_from_id: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  allowed_model_aliases: string[];
  created_at: string;
  updated_at: string;
}

/** 발급·로테이션 응답. `virtual_key` 원문은 이 응답에서만 볼 수 있습니다. */
export interface VirtualKeyCreateResponse extends VirtualKeyResponse {
  virtual_key: string;
}

export interface VirtualKeyCreateRequest {
  name: string;
  owner_type: VKOwnerType;
  owner_id: string;
  expires_at: string;
  allowed_model_aliases?: string[];
}

export interface VirtualKeyUpdateRequest {
  name?: string | null;
  allowed_model_aliases?: string[] | null;
  expires_at?: string | null;
}

export interface VirtualKeyRotateRequest {
  grace_period_hours?: number;
  reason?: string | null;
}

export interface VirtualKeyAuditEntry {
  occurred_at: string;
  actor_user_id: string;
  actor_role: string;
  action: string;
  resource_id: string;
  changes: Record<string, unknown>;
  result: string;
}

export interface VirtualKeyAuditResponse {
  key_id: string;
  rotation_chain: string[];
  entries: VirtualKeyAuditEntry[];
}

// ── 모델 카탈로그 ─────────────────────────────────────────────────────────────

/** 단가는 전부 문자열입니다. `Number()`로 바꾸면 정밀도가 깨집니다. */
export interface PricingResponse {
  id: string;
  model_alias: string;
  input_price_per_1k: string;
  output_price_per_1k: string;
  cache_write_price_per_1k: string;
  cache_read_price_per_1k: string;
  currency: string;
  effective_from: string;
  effective_until: string | null;
  source: string;
}

export interface PricingCreateRequest {
  input_price_per_1k: string;
  output_price_per_1k: string;
  cache_write_price_per_1k?: string;
  cache_read_price_per_1k?: string;
  effective_from: string;
  source?: string;
}

export interface ModelResponse {
  alias: string;
  display_name: string | null;
  provider: Provider;
  provider_model_id: string;
  region: string | null;
  supported_dialects: ApiDialect[];
  status: ModelStatus;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  supports_streaming: boolean;
  description: string | null;
  current_pricing: PricingResponse | null;
  created_at: string;
  updated_at: string;
}

export interface ModelCreateRequest {
  alias: string;
  display_name?: string | null;
  provider?: Provider;
  provider_model_id: string;
  region?: string | null;
  supported_dialects: ApiDialect[];
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  supports_streaming?: boolean;
  description?: string | null;
  pricing: PricingCreateRequest;
}

export interface ModelUpdateRequest {
  display_name?: string | null;
  provider_model_id?: string | null;
  region?: string | null;
  supported_dialects?: ApiDialect[] | null;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  supports_streaming?: boolean | null;
  description?: string | null;
}

export interface ModelStatusRequest {
  status: ModelStatus;
}

// ── 허용 모델 ─────────────────────────────────────────────────────────────────

export interface AllowedModelsRequest {
  model_aliases: string[];
}

export interface AllowedModelsResponse {
  scope: string;
  scope_id: string;
  model_aliases: string[];
}

/** 세 층(카탈로그 → 팀 → 사용자) 해석 결과. `resolved_from`이 이긴 층입니다. */
export interface EffectiveModelsResponse {
  user_id: string;
  model_aliases: string[];
  resolved_from: ResolvedFrom;
  narrowed_by_key: boolean;
}

// ── 서비스 토큰 ───────────────────────────────────────────────────────────────

export interface ServiceTokenResponse {
  id: string;
  name: string;
  token_prefix: string;
  expires_at: string;
  revoked_at: string | null;
  rotated_from_id: string | null;
  created_at: string;
}

/** 발급·로테이션 응답. `token` 원문은 이 응답에서만 볼 수 있습니다. */
export interface ServiceTokenCreateResponse extends ServiceTokenResponse {
  token: string;
}

export interface ServiceTokenCreateRequest {
  name: string;
  expires_in_days?: number;
}
