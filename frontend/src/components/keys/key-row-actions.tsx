'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Field, Input, Select } from '@/components/ui/field';
import { SecretRevealDialog } from '@/components/ui/secret-dialog';
import {
  revokeVirtualKeyAction,
  rotateVirtualKeyAction,
  updateVirtualKeyAction,
} from '@/lib/actions/virtual-keys';
import { toDateTimeLocalValue } from '@/lib/format/datetime';
import { REVOKE_REASON_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { RevokeReason, VKStatus, type VirtualKeyResponse } from '@/types/api';

function toIso(localValue: string): string {
  return localValue ? new Date(localValue).toISOString() : '';
}

/**
 * Virtual Key 행 조작 — 수정 / 로테이션 / 폐기.
 *
 * 폐기는 사유 없이 진행할 수 없습니다(backend 03 문서 감사 요구사항). 로테이션 결과 원문은
 * 발급과 같은 1회 노출 다이얼로그로 전달합니다.
 */
export function KeyRowActions({
  vkey,
  canManage = true,
  compact = false,
}: {
  vkey: VirtualKeyResponse;
  canManage?: boolean;
  compact?: boolean;
}) {
  const [editOpen, setEditOpen] = useState(false);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [rotated, setRotated] = useState<{ key: string; prefix: string } | null>(null);

  const [name, setName] = useState(vkey.name);
  const [expiresAt, setExpiresAt] = useState(
    vkey.expires_at ? toDateTimeLocalValue(vkey.expires_at) : '',
  );
  const [graceHours, setGraceHours] = useState('24');
  const [rotateReason, setRotateReason] = useState('');
  const [revokeReason, setRevokeReason] = useState<RevokeReason>(RevokeReason.OFFBOARDING);
  const [revokeNote, setRevokeNote] = useState('');

  const update = useAction(updateVirtualKeyAction, {
    successMessage: '키 정보를 수정했습니다',
    onSuccess: () => setEditOpen(false),
  });

  const rotate = useAction(rotateVirtualKeyAction, {
    onSuccess: (data) => {
      setRotateOpen(false);
      setRotated({ key: data.virtual_key, prefix: data.key_prefix });
    },
  });

  const revoke = useAction(revokeVirtualKeyAction, {
    successMessage: '키를 폐기했습니다',
    onSuccess: () => setRevokeOpen(false),
  });

  const active = vkey.status === VKStatus.ACTIVE;

  return (
    <div className="flex items-center justify-end gap-1">
      {canManage && !compact ? (
        <Button variant="ghost" size="sm" disabled={!active} onClick={() => setEditOpen(true)}>
          수정
        </Button>
      ) : null}
      {canManage ? (
        <Button variant="ghost" size="sm" disabled={!active} onClick={() => setRotateOpen(true)}>
          로테이션
        </Button>
      ) : null}
      <Button
        variant="ghost"
        size="sm"
        className="text-danger"
        disabled={vkey.status === VKStatus.REVOKED}
        onClick={() => setRevokeOpen(true)}
      >
        폐기
      </Button>

      {/* 수정 */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent
          title="Virtual Key 수정"
          description={vkey.key_prefix}
          footer={
            <>
              <Button variant="ghost" onClick={() => setEditOpen(false)} disabled={update.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={update.pending}
                onClick={() =>
                  void update.run(vkey.id, {
                    name,
                    ...(expiresAt ? { expires_at: toIso(expiresAt) } : {}),
                  })
                }
              >
                저장
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="키 이름" htmlFor={`key-name-${vkey.id}`} required>
              <Input
                id={`key-name-${vkey.id}`}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="만료 시각" htmlFor={`key-exp-${vkey.id}`}>
              <Input
                id={`key-exp-${vkey.id}`}
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      {/* 로테이션 */}
      <Dialog open={rotateOpen} onOpenChange={setRotateOpen}>
        <DialogContent
          title="Virtual Key 로테이션"
          description="새 키를 발급하고 기존 키를 유예 기간 뒤에 끊습니다."
          footer={
            <>
              <Button variant="ghost" onClick={() => setRotateOpen(false)} disabled={rotate.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={rotate.pending}
                onClick={() =>
                  void rotate.run(vkey.id, {
                    gracePeriodHours: Number(graceHours),
                    reason: rotateReason,
                  })
                }
              >
                로테이션
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="rounded-(--radius-base) border border-warning/30 bg-warning-soft px-3 py-2 text-xs text-warning">
              유예 기간 동안에는 기존 키와 새 키가 **모두** 통합니다. client 교체가 끝나는 데
              걸리는 시간만큼만 잡으세요.
            </div>
            <Field
              label="유예 시간 (시간)"
              htmlFor={`grace-${vkey.id}`}
              error={rotate.fieldErrors['grace_period_hours']}
              hint="0 을 넣으면 기존 키가 즉시 끊깁니다"
            >
              <Input
                id={`grace-${vkey.id}`}
                type="number"
                min={0}
                value={graceHours}
                onChange={(event) => setGraceHours(event.target.value)}
              />
            </Field>
            <Field label="사유" htmlFor={`rotate-reason-${vkey.id}`} hint="감사 로그에 남습니다">
              <Input
                id={`rotate-reason-${vkey.id}`}
                value={rotateReason}
                onChange={(event) => setRotateReason(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      {/* 폐기 */}
      <ConfirmDialog
        open={revokeOpen}
        onOpenChange={setRevokeOpen}
        title="Virtual Key 폐기"
        description={`${vkey.name} (${vkey.key_prefix}) 를 즉시 폐기합니다. 이 키를 쓰는 호출은 곧바로 실패합니다.`}
        confirmLabel="폐기"
        pending={revoke.pending}
        onConfirm={() => void revoke.run(vkey.id, { reason: revokeReason, note: revokeNote })}
      >
        <div className="space-y-3">
          <Field label="폐기 사유" htmlFor={`revoke-reason-${vkey.id}`} required>
            <Select
              id={`revoke-reason-${vkey.id}`}
              value={revokeReason}
              onChange={(event) => setRevokeReason(event.target.value as RevokeReason)}
            >
              {Object.values(RevokeReason).map((value) => (
                <option key={value} value={value}>
                  {REVOKE_REASON_LABEL[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="메모" htmlFor={`revoke-note-${vkey.id}`} hint="선택 사항. 감사 로그에 남습니다">
            <Input
              id={`revoke-note-${vkey.id}`}
              value={revokeNote}
              maxLength={255}
              onChange={(event) => setRevokeNote(event.target.value)}
            />
          </Field>
        </div>
      </ConfirmDialog>

      <SecretRevealDialog
        open={rotated !== null}
        onClose={() => setRotated(null)}
        title="로테이션 완료 — 새 Virtual Key"
        description={rotated ? `prefix: ${rotated.prefix}` : undefined}
        secret={rotated?.key ?? ''}
      >
        <p className="mt-3 text-xs text-muted-foreground">
          유예 기간이 끝나기 전에 client 설정을 새 키로 교체하세요.
        </p>
      </SecretRevealDialog>
    </div>
  );
}
