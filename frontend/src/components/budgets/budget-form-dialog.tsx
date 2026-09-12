'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Field, Input, Select } from '@/components/ui/field';
import { clearTeamBudgetAction, setTeamBudgetAction } from '@/lib/actions/budgets';
import { parseThresholds } from '@/lib/format/usage';
import { BUDGET_POLICY_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { BudgetPolicy } from '@/types/api';

/**
 * 팀 예산 설정·해제.
 *
 * **해제는 무제한이고 0 설정은 "쓸 수 없음"입니다.** 같은 화면에 두되 버튼을 분리하고
 * 문구를 다르게 씁니다 — 이 둘을 헷갈리면 상한이 장식이 되거나 팀 전체가 막힙니다.
 *
 * 경보 임계는 backend 가 `alert_level` 을 계산하는 근거입니다. 프론트는 계산하지 않고
 * 값만 전달합니다.
 */
export function BudgetFormDialog({
  teamId,
  teamName,
  currentLimit,
  currentPolicy,
  currentThresholds,
  configured,
}: {
  teamId: string;
  teamName: string;
  currentLimit?: string;
  currentPolicy?: BudgetPolicy;
  currentThresholds?: number[];
  configured: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [limit, setLimit] = useState(currentLimit ?? '');
  const [policy, setPolicy] = useState<BudgetPolicy>(currentPolicy ?? BudgetPolicy.HARD_BLOCK);
  const [thresholds, setThresholds] = useState((currentThresholds ?? [80, 90, 100]).join(','));

  const save = useAction(
    (input: { limit_usd: string; policy: BudgetPolicy; warn_thresholds: number[] }) =>
      setTeamBudgetAction(teamId, input),
    { successMessage: '팀 예산을 저장했습니다', onSuccess: () => setOpen(false) },
  );

  const clear = useAction(() => clearTeamBudgetAction(teamId), {
    successMessage: '예산을 해제했습니다. 이 팀은 무제한입니다',
    onSuccess: () => setConfirmClear(false),
  });

  return (
    <div className="flex gap-2">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="primary" size="sm">
            {configured ? '예산 수정' : '예산 설정'}
          </Button>
        </DialogTrigger>
        <DialogContent
          title={`${teamName} 월 예산`}
          description="기간 경계는 UTC 월입니다. 한도 변경은 즉시 유효하고 당월 소진에는 영향이 없습니다."
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={save.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={save.pending}
                onClick={() =>
                  void save.run({
                    limit_usd: limit,
                    policy,
                    warn_thresholds: parseThresholds(thresholds),
                  })
                }
              >
                저장
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field
              label="월 한도 (USD)"
              htmlFor="budget-limit"
              required
              hint="0 은 '쓸 수 없음'입니다. 무제한으로 두려면 저장하지 말고 해제하세요."
              error={save.fieldErrors['limit_usd']}
            >
              <Input
                id="budget-limit"
                value={limit}
                autoFocus
                inputMode="decimal"
                placeholder="1000.0000"
                onChange={(event) => setLimit(event.target.value)}
              />
            </Field>
            <Field label="초과 정책" htmlFor="budget-policy">
              <Select
                id="budget-policy"
                value={policy}
                onChange={(event) => setPolicy(event.target.value as BudgetPolicy)}
              >
                {Object.values(BudgetPolicy).map((value) => (
                  <option key={value} value={value}>
                    {BUDGET_POLICY_LABEL[value]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="경보 임계 (%)"
              htmlFor="budget-thresholds"
              hint="쉼표로 구분합니다. backend 가 이 값으로 경보 단계를 계산합니다."
              error={save.fieldErrors['warn_thresholds']}
            >
              <Input
                id="budget-thresholds"
                value={thresholds}
                onChange={(event) => setThresholds(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      {configured ? (
        <>
          <Button variant="dangerOutline" size="sm" onClick={() => setConfirmClear(true)}>
            예산 해제
          </Button>
          <ConfirmDialog
            open={confirmClear}
            onOpenChange={setConfirmClear}
            title="예산을 해제할까요?"
            description="해제하면 이 팀은 무제한이 됩니다. 차단 없이 비용이 쌓입니다."
            confirmLabel="해제"
            pending={clear.pending}
            onConfirm={() => void clear.run()}
          />
        </>
      ) : null}
    </div>
  );
}
