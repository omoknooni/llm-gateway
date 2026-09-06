import {
  ApiDialect,
  ModelStatus,
  ResolvedFrom,
  RevokeReason,
  UserRole,
  VKOwnerType,
  VKStatus,
} from '@/types/api';

/**
 * enum → 한국어 라벨과 색 톤.
 *
 * 표 전체에서 같은 값이 같은 색으로 보이게 한 곳에 모읍니다. 화면마다 색을 정하면
 * `REVOKED` 가 어떤 표에선 회색, 어떤 표에선 빨강이 됩니다.
 */
export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

export const USER_ROLE_LABEL: Record<UserRole, string> = {
  [UserRole.ADMIN]: '플랫폼 관리자',
  [UserRole.TEAM_LEADER]: '팀장',
  [UserRole.MEMBER]: '팀원',
};

export const USER_ROLE_TONE: Record<UserRole, Tone> = {
  [UserRole.ADMIN]: 'info',
  [UserRole.TEAM_LEADER]: 'success',
  [UserRole.MEMBER]: 'neutral',
};

export const VK_STATUS_LABEL: Record<VKStatus, string> = {
  [VKStatus.ACTIVE]: '활성',
  [VKStatus.ROTATED]: '로테이션됨',
  [VKStatus.REVOKED]: '폐기됨',
  [VKStatus.EXPIRED]: '만료됨',
};

export const VK_STATUS_TONE: Record<VKStatus, Tone> = {
  [VKStatus.ACTIVE]: 'success',
  // 유예 기간 동안은 아직 통하는 키입니다. 회색으로 묻으면 위험이 안 보입니다.
  [VKStatus.ROTATED]: 'warning',
  [VKStatus.REVOKED]: 'danger',
  [VKStatus.EXPIRED]: 'neutral',
};

export const VK_OWNER_TYPE_LABEL: Record<VKOwnerType, string> = {
  [VKOwnerType.TEAM]: '팀',
  [VKOwnerType.USER]: '개인',
};

export const REVOKE_REASON_LABEL: Record<RevokeReason, string> = {
  [RevokeReason.LOST]: '분실',
  [RevokeReason.OFFBOARDING]: '퇴사·이동',
  [RevokeReason.POLICY_VIOLATION]: '정책 위반',
  [RevokeReason.INCIDENT]: '보안 사고',
  [RevokeReason.ROTATION]: '로테이션',
  [RevokeReason.OTHER]: '기타',
};

export const MODEL_STATUS_LABEL: Record<ModelStatus, string> = {
  [ModelStatus.ACTIVE]: '활성',
  [ModelStatus.INACTIVE]: '비활성',
};

export const MODEL_STATUS_TONE: Record<ModelStatus, Tone> = {
  [ModelStatus.ACTIVE]: 'success',
  [ModelStatus.INACTIVE]: 'neutral',
};

export const DIALECT_LABEL: Record<ApiDialect, string> = {
  [ApiDialect.OPENAI_CHAT]: 'OpenAI 호환',
  [ApiDialect.ANTHROPIC_MESSAGES]: 'Anthropic Messages',
};

export const RESOLVED_FROM_LABEL: Record<ResolvedFrom, string> = {
  [ResolvedFrom.USER]: '개인 설정',
  [ResolvedFrom.TEAM]: '팀 설정',
  [ResolvedFrom.CATALOG]: '카탈로그 전체',
};

/**
 * 감사 로그의 `action` 은 `동사_명사` 형식입니다(backend 00 문서).
 * 모르는 값이 와도 화면이 비지 않게 원본을 그대로 돌려줍니다.
 */
const AUDIT_ACTION_LABEL: Record<string, string> = {
  CREATE_VIRTUAL_KEY: 'Virtual Key 발급',
  ROTATE_VIRTUAL_KEY: 'Virtual Key 로테이션',
  REVOKE_VIRTUAL_KEY: 'Virtual Key 폐기',
  UPDATE_VIRTUAL_KEY: 'Virtual Key 수정',
  EXPIRE_VIRTUAL_KEY: 'Virtual Key 만료',
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABEL[action] ?? action;
}
