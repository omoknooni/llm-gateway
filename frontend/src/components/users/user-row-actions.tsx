'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Checkbox, Field, Input, Select } from '@/components/ui/field';
import { deactivateUserAction, transferUserTeamAction, updateUserAction } from '@/lib/actions/users';
import { USER_ROLE_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { UserRole, type TeamResponse, type UserResponse } from '@/types/api';

/**
 * 사용자 행 조작 — 수정 / 팀 이동 / 비활성화.
 *
 * 비활성화와 팀 이동은 소유 VK 에 파급됩니다. 응답의 `revoked_virtual_keys`,
 * `affected_virtual_keys`, `cache_invalidated` 를 결과 다이얼로그에 그대로 보여줍니다 —
 * "몇 개가 끊겼는지" 모르고 넘어가면 나중에 client 장애로 되돌아옵니다(01 문서).
 */
export function UserRowActions({ user, teams }: { user: UserResponse; teams: TeamResponse[] }) {
  const [editOpen, setEditOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [impact, setImpact] = useState<{ title: string; lines: string[] } | null>(null);

  const [displayName, setDisplayName] = useState(user.display_name);
  const [role, setRole] = useState<UserRole>(user.role);
  const [isActive, setIsActive] = useState(user.is_active);

  const [targetTeamId, setTargetTeamId] = useState(user.team_id ?? '');
  const [reason, setReason] = useState('');

  const update = useAction(updateUserAction, {
    successMessage: '사용자 정보를 수정했습니다',
    onSuccess: () => setEditOpen(false),
  });

  const transfer = useAction(transferUserTeamAction, {
    onSuccess: (data) => {
      setTransferOpen(false);
      setImpact({
        title: '팀 이동 완료',
        lines: [
          `인증 캐시가 지워진 Virtual Key: ${data.affected_virtual_keys}개`,
          data.cache_invalidated
            ? '캐시 무효화가 반영되었습니다.'
            : '캐시 무효화에 실패했습니다. 설정 → 캐시에서 재시도하세요.',
        ],
      });
    },
  });

  const deactivate = useAction(deactivateUserAction, {
    onSuccess: (data) => {
      setDeactivateOpen(false);
      setImpact({
        title: '사용자 비활성화 완료',
        lines: [
          `폐기된 Virtual Key: ${data.revoked_virtual_keys}개`,
          data.cache_invalidated
            ? '캐시 무효화가 반영되었습니다.'
            : '캐시 무효화에 실패했습니다. 설정 → 캐시에서 재시도하세요.',
        ],
      });
    },
  });

  return (
    <div className="flex items-center justify-end gap-1">
      <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>
        수정
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setTransferOpen(true)}>
        팀 이동
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="text-danger"
        disabled={!user.is_active}
        onClick={() => setDeactivateOpen(true)}
      >
        비활성화
      </Button>

      {/* 수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent
          title="사용자 수정"
          description={user.email}
          footer={
            <>
              <Button variant="ghost" onClick={() => setEditOpen(false)} disabled={update.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={update.pending}
                onClick={() =>
                  void update.run(user.id, {
                    display_name: displayName,
                    role,
                    is_active: isActive,
                  })
                }
              >
                저장
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="표시명" htmlFor={`dn-${user.id}`} required>
              <Input
                id={`dn-${user.id}`}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
            <Field
              label="역할"
              htmlFor={`role-${user.id}`}
              hint="마지막 관리자의 역할은 backend 가 낮추지 못하게 막습니다"
            >
              <Select
                id={`role-${user.id}`}
                value={role}
                onChange={(event) => setRole(event.target.value as UserRole)}
              >
                {Object.values(UserRole).map((value) => (
                  <option key={value} value={value}>
                    {USER_ROLE_LABEL[value]}
                  </option>
                ))}
              </Select>
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={isActive}
                onChange={(event) => setIsActive(event.target.checked)}
              />
              활성 사용자
            </label>
          </div>
        </DialogContent>
      </Dialog>

      {/* 팀 이동 */}
      <Dialog open={transferOpen} onOpenChange={setTransferOpen}>
        <DialogContent
          title="팀 이동"
          description="소유한 Virtual Key 의 인증 캐시가 함께 무효화됩니다."
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => setTransferOpen(false)}
                disabled={transfer.pending}
              >
                취소
              </Button>
              <Button
                variant="primary"
                loading={transfer.pending}
                disabled={targetTeamId === (user.team_id ?? '')}
                onClick={() =>
                  void transfer.run(user.id, { teamId: targetTeamId || null, reason })
                }
              >
                이동
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="이동할 팀" htmlFor={`team-${user.id}`}>
              <Select
                id={`team-${user.id}`}
                value={targetTeamId}
                onChange={(event) => setTargetTeamId(event.target.value)}
              >
                <option value="">팀 없음</option>
                {teams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="사유" htmlFor={`reason-${user.id}`} hint="감사 로그에 남습니다">
              <Input
                id={`reason-${user.id}`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      {/* 비활성화 */}
      <ConfirmDialog
        open={deactivateOpen}
        onOpenChange={setDeactivateOpen}
        title="사용자 비활성화"
        description={`${user.display_name} (${user.email}) 을 비활성화하고 소유한 Virtual Key 를 모두 폐기합니다.`}
        confirmLabel="비활성화"
        pending={deactivate.pending}
        onConfirm={() => void deactivate.run(user.id)}
      />

      {/* 파급 결과 */}
      <Dialog open={impact !== null} onOpenChange={(open) => !open && setImpact(null)}>
        <DialogContent
          title={impact?.title ?? ''}
          footer={
            <Button variant="primary" onClick={() => setImpact(null)}>
              확인
            </Button>
          }
        >
          <ul className="space-y-1 text-sm">
            {impact?.lines.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </DialogContent>
      </Dialog>
    </div>
  );
}
