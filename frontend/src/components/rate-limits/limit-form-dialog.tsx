'use client';

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Field, Input } from '@/components/ui/field';
import { deleteRateLimitAction, setRateLimitAction } from '@/lib/actions/rate-limits';
import { LIMIT_FIELD_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import {
  LIMIT_FIELDS,
  RateLimitScope,
  type ConflictingChild,
  type RateLimitResponse,
} from '@/types/api';

/**
 * rate limit 설정.
 *
 * 세 한도는 **독립**이고 빈 칸은 `null` = "이 층에서 정의하지 않음"입니다. 상위로 폴백하는
 * 것과 정의 자체를 지우는 것은 다르므로 해제 버튼이 따로 있습니다(backend 06 문서).
 *
 * 상위보다 큰 하위 설정이 남아 있으면 backend 가 거절하지 않고 `conflicting_children` 으로
 * 알려 줍니다. 자동으로 깎지 않는 이유는 관리자가 의도하지 않은 값 변경이 되기 때문입니다.
 * 그래서 저장에 성공해도 **충돌이 있으면 다이얼로그를 닫지 않고** 그대로 보여줍니다.
 */
export function LimitFormDialog({
  scope,
  scopeId,
  modelAlias,
  label,
  current,
  triggerLabel,
  size = 'sm',
}: {
  scope: RateLimitScope;
  scopeId: string | null;
  modelAlias?: string;
  label: string;
  current?: RateLimitResponse | null;
  triggerLabel?: string;
  size?: 'sm' | 'md';
}) {
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [conflicts, setConflicts] = useState<ConflictingChild[]>([]);
  const [values, setValues] = useState({
    rpm_limit: current?.rpm_limit?.toString() ?? '',
    tpm_limit: current?.tpm_limit?.toString() ?? '',
    concurrency_limit: current?.concurrency_limit?.toString() ?? '',
  });

  const save = useAction(
    (input: typeof values) => setRateLimitAction({ scope, scopeId, ...(modelAlias ? { modelAlias } : {}) }, input),
    {
      successMessage: '한도를 저장했습니다',
      onSuccess: (data) => {
        setConflicts(data.conflicting_children);
        if (data.conflicting_children.length === 0) setOpen(false);
      },
    },
  );

  const remove = useAction(
    () => deleteRateLimitAction(scope, scopeId, modelAlias),
    {
      successMessage: '한도 정의를 제거했습니다. 이제 상위 층을 따릅니다',
      onSuccess: () => {
        setConfirmDelete(false);
        setOpen(false);
      },
    },
  );

  return (
    <div className="inline-flex gap-1.5">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button size={size} variant={current ? 'secondary' : 'ghost'}>
            {triggerLabel ?? (current ? '수정' : '설정')}
          </Button>
        </DialogTrigger>
        <DialogContent
          title={`${label} 한도`}
          description={
            modelAlias
              ? `모델 ${modelAlias} 에만 적용됩니다.`
              : '모델을 지정하지 않은 한도입니다. 이 대상의 모든 모델에 적용됩니다.'
          }
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={save.pending}>
                취소
              </Button>
              <Button variant="primary" loading={save.pending} onClick={() => void save.run(values)}>
                저장
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            {LIMIT_FIELDS.map((field) => (
              <Field
                key={field}
                label={LIMIT_FIELD_LABEL[field]}
                htmlFor={`limit-${field}`}
                hint="비우면 이 층에서 정의하지 않고 상위 한도를 따릅니다."
                error={save.fieldErrors[field]}
              >
                <Input
                  id={`limit-${field}`}
                  value={values[field]}
                  inputMode="numeric"
                  placeholder="상위 상속"
                  onChange={(event) =>
                    setValues((currentValues) => ({ ...currentValues, [field]: event.target.value }))
                  }
                />
              </Field>
            ))}

            {conflicts.length > 0 ? (
              <div className="rounded-(--radius-base) border border-warning/35 bg-warning-soft px-3 py-2">
                <p className="text-xs font-medium text-warning">
                  저장했습니다. 다만 이 한도보다 큰 하위 설정이 남아 있습니다.
                </p>
                <ul className="mt-1.5 space-y-1 text-xs text-warning">
                  {conflicts.map((child) => (
                    <li key={child.scope_id} className="font-mono">
                      {child.scope_id} ·{' '}
                      {Object.entries(child.exceeds)
                        .map(
                          ([field, values_]) =>
                            `${LIMIT_FIELD_LABEL[field] ?? field} ${values_.child} > ${values_.parent}`,
                        )
                        .join(', ')}
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-xs text-warning">
                  자동으로 깎지 않습니다. 하위 설정을 직접 정리하세요.
                </p>
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {current ? (
        <>
          <Button size={size} variant="ghost" onClick={() => setConfirmDelete(true)}>
            해제
          </Button>
          <ConfirmDialog
            open={confirmDelete}
            onOpenChange={setConfirmDelete}
            title="한도 정의를 제거할까요?"
            description="이 층의 정의가 사라지고 상위 한도를 따릅니다. 값을 비워 저장하는 것과 다릅니다."
            confirmLabel="제거"
            pending={remove.pending}
            onConfirm={() => void remove.run()}
          />
        </>
      ) : null}
    </div>
  );
}

/** 한도 값 표시. `null` 은 정의 없음이므로 `0` 이나 `-` 와 다르게 읽혀야 합니다. */
export function LimitValues({ config }: { config: RateLimitResponse | null }) {
  if (!config) return <span className="text-xs text-muted-foreground">정의 없음 (상속)</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {LIMIT_FIELDS.map((field) =>
        config[field] === null ? null : (
          <Badge key={field} tone="neutral" className="num">
            {LIMIT_FIELD_LABEL[field]} {config[field]}
          </Badge>
        ),
      )}
    </span>
  );
}
