'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { createPricingAction } from '@/lib/actions/models';
import { toDateTimeLocalValue } from '@/lib/format/datetime';
import { useAction } from '@/lib/use-action';

import { PricingFields, emptyPricing, type PricingFormValue } from './pricing-fields';

/**
 * 단가 등록.
 *
 * 새 단가를 넣으면 기존 구간이 닫히고 새 구간이 열립니다. 구간이 겹치면 backend 가 409 로
 * 막습니다 — 화면은 그 메시지를 그대로 보여주고 임의로 값을 조정하지 않습니다.
 */
export function AddPricingDialog({ alias }: { alias: string }) {
  const [open, setOpen] = useState(false);
  const [pricing, setPricing] = useState<PricingFormValue>(() =>
    emptyPricing(toDateTimeLocalValue(new Date().toISOString())),
  );

  const { run, pending, fieldErrors } = useAction(createPricingAction, {
    successMessage: '단가를 등록했습니다',
    onSuccess: () => setOpen(false),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          단가 등록
        </Button>
      </DialogTrigger>
      <DialogContent
        title="단가 등록"
        description={alias}
        className="w-[min(94vw,40rem)]"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button variant="primary" loading={pending} onClick={() => void run(alias, pricing)}>
              등록
            </Button>
          </>
        }
      >
        <PricingFields
          value={pricing}
          onChange={setPricing}
          fieldErrors={fieldErrors}
          idPrefix={`pricing-${alias}`}
        />
      </DialogContent>
    </Dialog>
  );
}
