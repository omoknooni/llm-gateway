'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Field, Select } from '@/components/ui/field';
import { revokeAllTeamKeysAction } from '@/lib/actions/teams';
import { REVOKE_REASON_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { RevokeReason } from '@/types/api';

/**
 * 팀 소유 VK 일괄 폐기.
 *
 * 되돌릴 수 없는 조작이라 팀 이름을 그대로 입력해야 실행됩니다. 예/아니오 다이얼로그로
 * 끝내면 "확인"을 반사적으로 누르게 됩니다.
 */
export function RevokeAllKeysCard({ teamId, teamName }: { teamId: string; teamName: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<RevokeReason>(RevokeReason.INCIDENT);
  const [result, setResult] = useState<{ revoked: number; cacheOk: boolean } | null>(null);

  const { run, pending } = useAction(revokeAllTeamKeysAction, {
    onSuccess: (data) => {
      setResult({ revoked: data.revoked_virtual_keys, cacheOk: data.cache_invalidated });
      setOpen(false);
    },
  });

  return (
    <Card className="border-danger/35">
      <CardHeader
        title="팀 Virtual Key 일괄 폐기"
        description="이 팀이 소유한 모든 Virtual Key 를 즉시 폐기합니다. 되돌릴 수 없습니다."
        actions={
          <Button variant="dangerOutline" size="sm" onClick={() => setOpen(true)}>
            일괄 폐기
          </Button>
        }
      />
      {result ? (
        <CardBody>
          <p className="text-sm">
            {result.revoked}개의 Virtual Key 를 폐기했습니다.
            {result.cacheOk ? (
              <span className="ml-1 text-muted-foreground">캐시 무효화까지 반영되었습니다.</span>
            ) : (
              <span className="ml-1 text-warning">
                캐시 무효화에 실패했습니다. 설정 → 캐시에서 재시도하세요.
              </span>
            )}
          </p>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="팀 Virtual Key 일괄 폐기"
        description="폐기된 키는 복구할 수 없고, 이 키를 쓰던 모든 client 호출이 즉시 실패합니다."
        confirmLabel="모두 폐기"
        confirmPhrase={teamName}
        pending={pending}
        onConfirm={() => void run(teamId, { confirmTeamName: teamName, reason })}
      >
        <Field label="폐기 사유" htmlFor="revoke-all-reason" hint="감사 로그에 남습니다">
          <Select
            id="revoke-all-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value as RevokeReason)}
          >
            {Object.values(RevokeReason).map((value) => (
              <option key={value} value={value}>
                {REVOKE_REASON_LABEL[value]}
              </option>
            ))}
          </Select>
        </Field>
      </ConfirmDialog>
    </Card>
  );
}
