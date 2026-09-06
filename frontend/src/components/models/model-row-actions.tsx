'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Checkbox, Field, Input, Textarea } from '@/components/ui/field';
import { setModelStatusAction, updateModelAction } from '@/lib/actions/models';
import { DIALECT_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { ApiDialect, ModelStatus, type ModelResponse } from '@/types/api';

export function ModelRowActions({ model }: { model: ModelResponse }) {
  const [editOpen, setEditOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  const [displayName, setDisplayName] = useState(model.display_name ?? '');
  const [providerModelId, setProviderModelId] = useState(model.provider_model_id);
  const [region, setRegion] = useState(model.region ?? '');
  const [dialects, setDialects] = useState<ApiDialect[]>(model.supported_dialects);
  const [maxInput, setMaxInput] = useState(model.max_input_tokens?.toString() ?? '');
  const [maxOutput, setMaxOutput] = useState(model.max_output_tokens?.toString() ?? '');
  const [streaming, setStreaming] = useState(model.supports_streaming);
  const [description, setDescription] = useState(model.description ?? '');

  const update = useAction(updateModelAction, {
    successMessage: '모델 정보를 수정했습니다',
    onSuccess: () => setEditOpen(false),
  });

  const status = useAction(setModelStatusAction, {
    successMessage: '모델 상태를 변경했습니다',
    onSuccess: () => setDeactivateOpen(false),
  });

  const isActive = model.status === ModelStatus.ACTIVE;

  return (
    <div className="flex items-center justify-end gap-1">
      <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>
        수정
      </Button>
      {isActive ? (
        <Button
          variant="ghost"
          size="sm"
          className="text-danger"
          onClick={() => setDeactivateOpen(true)}
        >
          비활성화
        </Button>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          loading={status.pending}
          onClick={() => void status.run(model.alias, ModelStatus.ACTIVE)}
        >
          활성화
        </Button>
      )}

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent
          title="모델 수정"
          description={model.alias}
          className="w-[min(94vw,40rem)]"
          footer={
            <>
              <Button variant="ghost" onClick={() => setEditOpen(false)} disabled={update.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={update.pending}
                onClick={() =>
                  void update.run(model.alias, {
                    display_name: displayName,
                    provider_model_id: providerModelId,
                    region,
                    supported_dialects: dialects,
                    max_input_tokens: maxInput,
                    max_output_tokens: maxOutput,
                    supports_streaming: streaming,
                    description,
                  })
                }
              >
                저장
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="표시명" htmlFor={`dn-${model.alias}`}>
                <Input
                  id={`dn-${model.alias}`}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </Field>
              <Field label="provider 모델 ID" htmlFor={`pid-${model.alias}`} required>
                <Input
                  id={`pid-${model.alias}`}
                  value={providerModelId}
                  onChange={(event) => setProviderModelId(event.target.value)}
                />
              </Field>
              <Field label="리전" htmlFor={`region-${model.alias}`}>
                <Input
                  id={`region-${model.alias}`}
                  value={region}
                  onChange={(event) => setRegion(event.target.value)}
                />
              </Field>
              <Field label="최대 입력 토큰" htmlFor={`mi-${model.alias}`}>
                <Input
                  id={`mi-${model.alias}`}
                  type="number"
                  min={1}
                  value={maxInput}
                  onChange={(event) => setMaxInput(event.target.value)}
                />
              </Field>
              <Field label="최대 출력 토큰" htmlFor={`mo-${model.alias}`}>
                <Input
                  id={`mo-${model.alias}`}
                  type="number"
                  min={1}
                  value={maxOutput}
                  onChange={(event) => setMaxOutput(event.target.value)}
                />
              </Field>
            </div>

            <Field label="지원 방언" required error={update.fieldErrors['supported_dialects']}>
              <div className="flex flex-wrap gap-3">
                {Object.values(ApiDialect).map((dialect) => (
                  <label key={dialect} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={dialects.includes(dialect)}
                      onChange={() =>
                        setDialects((current) =>
                          current.includes(dialect)
                            ? current.filter((item) => item !== dialect)
                            : [...current, dialect],
                        )
                      }
                    />
                    {DIALECT_LABEL[dialect]}
                  </label>
                ))}
              </div>
            </Field>

            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={streaming}
                onChange={(event) => setStreaming(event.target.checked)}
              />
              스트리밍 지원
            </label>

            <Field label="설명" htmlFor={`desc-${model.alias}`}>
              <Textarea
                id={`desc-${model.alias}`}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deactivateOpen}
        onOpenChange={setDeactivateOpen}
        title="모델 비활성화"
        description={`${model.alias} 을 비활성화하면 이 모델을 지정한 client 호출이 거절되기 시작합니다. 카탈로그에서 삭제되지는 않습니다.`}
        confirmLabel="비활성화"
        pending={status.pending}
        onConfirm={() => void status.run(model.alias, ModelStatus.INACTIVE)}
      />
    </div>
  );
}
