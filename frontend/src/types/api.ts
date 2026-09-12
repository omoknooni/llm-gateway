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

// ── 예산 (backend M6) ─────────────────────────────────────────────────────────

export const BudgetScope = {
  TEAM: 'TEAM',
  USER: 'USER',
} as const;
export type BudgetScope = (typeof BudgetScope)[keyof typeof BudgetScope];

export const BudgetPeriod = { MONTHLY: 'MONTHLY' } as const;
export type BudgetPeriod = (typeof BudgetPeriod)[keyof typeof BudgetPeriod];

export const BudgetPolicy = {
  HARD_BLOCK: 'HARD_BLOCK',
  SOFT_WARN: 'SOFT_WARN',
} as const;
export type BudgetPolicy = (typeof BudgetPolicy)[keyof typeof BudgetPolicy];

/** 소진 경보 단계. **backend 가 `warn_thresholds` 로 계산합니다** — 프론트가 다시 계산하지 않습니다. */
export const AlertLevel = {
  NORMAL: 'NORMAL',
  WARNING: 'WARNING',
  CRITICAL: 'CRITICAL',
  EXCEEDED: 'EXCEEDED',
} as const;
export type AlertLevel = (typeof AlertLevel)[keyof typeof AlertLevel];

export interface BudgetSetRequest {
  limit_usd: string;
  policy?: BudgetPolicy;
  period_type?: BudgetPeriod;
  warn_thresholds?: number[];
  effective_from?: string | null;
}

export interface BudgetConfigResponse {
  id: string;
  scope: BudgetScope;
  scope_id: string;
  limit_usd: string;
  period_type: BudgetPeriod;
  policy: BudgetPolicy;
  warn_thresholds: number[];
  effective_from: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** `source`는 소진값을 Redis(집행 카운터)에서 읽었는지 DB 에서 읽었는지입니다. 숨기지 않습니다. */
export interface BudgetUsageItem {
  scope: BudgetScope;
  scope_id: string;
  name: string | null;
  limit_usd: string;
  used_usd: string;
  remaining_usd: string;
  usage_pct: string;
  policy: BudgetPolicy;
  alert_level: AlertLevel;
  source: string;
}

export interface BudgetSummaryResponse {
  period: string;
  /** 항목별 출처가 섞이면 `mixed` 입니다. */
  source: string;
  items: BudgetUsageItem[];
}

export interface AllocationItem {
  user_id: string;
  limit_usd: string;
}

/** **전체 교체**입니다. 목록에 없는 멤버의 배분은 해제됩니다. */
export interface AllocationSetRequest {
  allocations: AllocationItem[];
  policy?: BudgetPolicy;
  warn_thresholds?: number[];
}

export interface AllocationEntry {
  user_id: string;
  display_name: string;
  email: string;
  limit_usd: string;
  used_usd: string;
  usage_pct: string;
  alert_level: AlertLevel;
  source: string;
}

export interface AllocationResponse {
  team_id: string;
  period: string;
  team_limit_usd: string;
  allocated_usd: string;
  unallocated_usd: string;
  allocations: AllocationEntry[];
}

export interface UsageBreakdownItem {
  key: string;
  name: string | null;
  cost_usd: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface TeamBudgetUsageResponse {
  period: string;
  budget: BudgetUsageItem;
  by_member: UsageBreakdownItem[];
  by_model: UsageBreakdownItem[];
}

export interface UserBudgetUsageResponse {
  period: string;
  budget: BudgetUsageItem;
  by_model: UsageBreakdownItem[];
}

/** 둘 다 null 이면 예산 미설정 = 무제한입니다. */
export interface MyBudgetResponse {
  period: string;
  user: BudgetUsageItem | null;
  team: BudgetUsageItem | null;
}

export interface UnsetBudgetTarget {
  id: string;
  name: string;
  team_id: string | null;
}

export interface UnsetBudgetResponse {
  teams: UnsetBudgetTarget[];
  users: UnsetBudgetTarget[];
}

export interface ReseedItem {
  scope: BudgetScope;
  scope_id: string;
  period: string;
  used_usd: string;
}

/** 운영 예외입니다. 사유가 필수이고 감사에 before/after 가 남습니다. */
export interface ReseedRequest {
  items: ReseedItem[];
  reason: string;
}

export interface ReseedResultItem {
  scope: BudgetScope;
  scope_id: string;
  period: string;
  before_usd: string | null;
  after_usd: string;
}

export interface ReseedResponse {
  items: ReseedResultItem[];
}

// ── rate limit (backend M8) ───────────────────────────────────────────────────

export const RateLimitScope = {
  GLOBAL: 'GLOBAL',
  TEAM: 'TEAM',
  USER: 'USER',
  VIRTUAL_KEY: 'VIRTUAL_KEY',
} as const;
export type RateLimitScope = (typeof RateLimitScope)[keyof typeof RateLimitScope];

/** 한도 종류. 셋은 독립이고 폴백도 **종류별로** 일어납니다(backend 06 문서). */
export const LIMIT_FIELDS = ['rpm_limit', 'tpm_limit', 'concurrency_limit'] as const;
export type LimitField = (typeof LIMIT_FIELDS)[number];

/** `null` 은 "이 층에서 정의하지 않음"이고, 행 삭제는 `DELETE` 입니다. 셋 다 null 은 422. */
export interface RateLimitSetRequest {
  rpm_limit?: number | null;
  tpm_limit?: number | null;
  concurrency_limit?: number | null;
}

export interface RateLimitResponse {
  id: string;
  scope: RateLimitScope;
  scope_id: string | null;
  model_alias: string | null;
  rpm_limit: number | null;
  tpm_limit: number | null;
  concurrency_limit: number | null;
  /** **null 은 "계산하지 않음"** 입니다. 배지가 필요하면 `/tree` 나 `/effective` 를 봅니다. */
  exceeds_parent: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface RateLimitListResponse {
  items: RateLimitResponse[];
}

export interface ResolvedLimitResponse {
  value: number | null;
  resolved_from: string | null;
  config_id: string | null;
}

/** 주체 축과 전역 축은 **따로** 옵니다. 둘 다 통과해야 요청이 진행됩니다. */
export interface EffectiveLimitsResponse {
  subject: Record<string, string | null>;
  effective_limits: Record<string, ResolvedLimitResponse>;
  global_limits: Record<string, ResolvedLimitResponse>;
}

export interface RateLimitTreeMember {
  user_id: string;
  display_name: string;
  own: RateLimitResponse | null;
  effective_limits: Record<string, ResolvedLimitResponse>;
}

export interface RateLimitTreeResponse {
  team_id: string;
  team_name: string;
  team_limits: RateLimitResponse | null;
  members: RateLimitTreeMember[];
}

export interface ConflictingChild {
  scope_id: string;
  exceeds: Record<string, { child: number; parent: number }>;
}

/** 상위보다 큰 하위 설정은 **거절하지 않고 알립니다**. 연쇄 자동 조정을 하지 않습니다. */
export interface RateLimitSetResponse {
  config: RateLimitResponse;
  conflicting_children: ConflictingChild[];
}

export interface RateLimitUsageEntry {
  scope: RateLimitScope;
  scope_id: string | null;
  model_alias: string | null;
  limit_value: number | null;
  current_value: number | null;
  usage_pct: number | null;
}

/** best-effort 입니다. `available=false` 는 오류가 아니라 정상 상태 중 하나입니다. */
export interface RateLimitUsageResponse {
  available: boolean;
  reason: string | null;
  entries: RateLimitUsageEntry[];
}

// ── 사용량·비용 (backend M7) ──────────────────────────────────────────────────

export const UsageAxis = {
  TEAM: 'TEAM',
  USER: 'USER',
  MODEL: 'MODEL',
  VIRTUAL_KEY: 'VIRTUAL_KEY',
} as const;
export type UsageAxis = (typeof UsageAxis)[keyof typeof UsageAxis];

export const UsageMetric = {
  COST: 'COST',
  REQUESTS: 'REQUESTS',
  TOKENS: 'TOKENS',
} as const;
export type UsageMetric = (typeof UsageMetric)[keyof typeof UsageMetric];

export const TrendGranularity = {
  DAY: 'DAY',
  MONTH: 'MONTH',
} as const;
export type TrendGranularity = (typeof TrendGranularity)[keyof typeof TrendGranularity];

/** 금액·비율은 문자열, 토큰·호출 수는 number 입니다(backend 스키마 그대로). */
export interface UsageTotals {
  request_count: number;
  success_count: number;
  error_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_write_tokens: number;
  cache_read_tokens: number;
  estimated_cost_usd: string;
  failure_rate_pct: string;
  avg_latency_ms: number;
}

export interface LeaderboardEntry {
  key: string;
  name: string | null;
  totals: UsageTotals;
}

export interface LeaderboardResponse {
  axis: UsageAxis;
  metric: UsageMetric;
  from_date: string;
  to_date: string;
  items: LeaderboardEntry[];
}

export interface UsageOverviewResponse {
  from_date: string;
  to_date: string;
  totals: UsageTotals;
  top_teams: LeaderboardEntry[];
  top_users: LeaderboardEntry[];
  top_models: LeaderboardEntry[];
}

export interface UsageTrendPoint {
  /** `YYYY-MM-DD`(일) 또는 `YYYY-MM`(월). */
  bucket: string;
  totals: UsageTotals;
}

/** 값이 없는 버킷은 **행이 없습니다**. 채우는 것은 기간을 아는 화면 몫입니다. */
export interface UsageTrendResponse {
  granularity: TrendGranularity;
  from_date: string;
  to_date: string;
  points: UsageTrendPoint[];
}

export interface AuthEventSummaryItem {
  outcome: string;
  /** **묶음 창을 펼친 실제 실패 수**입니다. `event_rows` 로 세면 과소 계상됩니다. */
  occurrence_count: number;
  event_rows: number;
}

export interface AuthEventSummaryResponse {
  from_date: string;
  to_date: string;
  total_occurrences: number;
  items: AuthEventSummaryItem[];
}
