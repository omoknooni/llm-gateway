'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Field, Input } from '@/components/ui/field';
import { reseedBudgetUsageAction } from '@/lib/actions/budgets';
import { useAction } from '@/lib/use-action';
import type { BudgetScope } from '@/types/api';

/**
 * 소진값 재시드.
 *
 * **운영 예외입니다.** control plane 이 gateway 의 집행 카운터를 쓰는 유일한 경로라 사유가
 * 필수이고 감사에 before/after 가 남습니다(backend 05 문서). 일반 저장 버튼과 같은 무게로
 * 보이지 않게 위험 버튼으로 둡니다.
 */
export function ReseedDialog({
  scope,
  scopeId,
  period,
  currentUsed,
  label,
}: {
  scope: BudgetScope;
  scopeId: string;
  period: string;
  currentUsed: string;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(currentUsed);
  const [reason, setReason] = useState('');

  const { run, pending, fieldErrors } = useAction(reseedBudgetUsageAction, {
    successMessage: '소진값을 재시드했습니다',
    onSuccess: () => {
      setOpen(false);
      setReason('');
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="dangerOutline" size="sm">
          소진값 재시드
        </Button>
      </DialogTrigger>
      <DialogContent
        title={`${label} 소진값 재시드`}
        description={`${period} 기간의 집행 카운터를 직접 덮어씁니다. 되돌리려면 다시 재시드해야 합니다.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant="danger"
              loading={pending}
              onClick={() => void run({ scope, scope_id: scopeId, period, used_usd: used, reason })}
            >
              재시드
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field
            label="새 소진값 (USD)"
            htmlFor="reseed-used"
            required
            hint={`현재 값: ${currentUsed}`}
            error={fieldErrors['used_usd']}
          >
            <Input
              id="reseed-used"
              value={used}
              inputMode="decimal"
              onChange={(event) => setUsed(event.target.value)}
            />
          </Field>
          <Field
            label="사유"
            htmlFor="reseed-reason"
            required
            hint="감사 로그에 그대로 남습니다."
            error={fieldErrors['reason']}
          >
            <Input
              id="reseed-reason"
              value={reason}
              placeholder="예: gateway 장애로 카운터 유실, DB 집계값으로 복구"
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}
