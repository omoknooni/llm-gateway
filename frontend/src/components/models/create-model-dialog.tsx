'use client';

import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Checkbox, Field, Input, Textarea } from '@/components/ui/field';
import { createModelAction } from '@/lib/actions/models';
import { toDateTimeLocalValue } from '@/lib/format/datetime';
import { DIALECT_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { ApiDialect } from '@/types/api';

import { PricingFields, emptyPricing, type PricingFormValue } from './pricing-fields';

export function CreateModelDialog() {
  const [open, setOpen] = useState(false);
  const [alias, setAlias] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [providerModelId, setProviderModelId] = useState('');
  const [region, setRegion] = useState('');
  const [dialects, setDialects] = useState<ApiDialect[]>([
    ApiDialect.OPENAI_CHAT,
    ApiDialect.ANTHROPIC_MESSAGES,
  ]);
  const [maxInput, setMaxInput] = useState('');
  const [maxOutput, setMaxOutput] = useState('');
  const [streaming, setStreaming] = useState(true);
  const [description, setDescription] = useState('');
  const [pricing, setPricing] = useState<PricingFormValue>(() =>
    emptyPricing(toDateTimeLocalValue(new Date().toISOString())),
  );

  const { run, pending, fieldErrors } = useAction(createModelAction, {
    successMessage: '모델을 등록했습니다',
    onSuccess: () => setOpen(false),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          <Plus />모델 등록
        </Button>
      </DialogTrigger>
      <DialogContent
        title="모델 등록"
        description="단가를 함께 등록합니다. 단가 없는 모델은 사용량이 비용으로 환산되지 않습니다."
        className="w-[min(94vw,44rem)]"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={pending}
              onClick={() =>
                void run({
                  alias,
                  display_name: displayName,
                  provider_model_id: providerModelId,
                  region,
                  supported_dialects: dialects,
                  max_input_tokens: maxInput,
                  max_output_tokens: maxOutput,
                  supports_streaming: streaming,
                  description,
                  pricing,
                })
              }
            >
              등록
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="alias"
              htmlFor="model-alias"
              required
              error={fieldErrors['alias']}
              hint="client 가 요청에 쓰는 이름입니다. 나중에 바꿀 수 없습니다."
            >
              <Input
                id="model-alias"
                value={alias}
                autoFocus
                placeholder="claude-sonnet-4"
                onChange={(event) => setAlias(event.target.value)}
              />
            </Field>
            <Field label="표시명" htmlFor="model-display-name">
              <Input
                id="model-display-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
            <Field
              label="provider 모델 ID"
              htmlFor="model-provider-id"
              required
              error={fieldErrors['provider_model_id']}
              hint="Bedrock 의 모델 ID 또는 inference profile ARN"
            >
              <Input
                id="model-provider-id"
                value={providerModelId}
                onChange={(event) => setProviderModelId(event.target.value)}
              />
            </Field>
            <Field label="리전" htmlFor="model-region" hint="비우면 배포 기본 리전을 씁니다">
              <Input
                id="model-region"
                value={region}
                placeholder="ap-northeast-2"
                onChange={(event) => setRegion(event.target.value)}
              />
            </Field>
            <Field label="최대 입력 토큰" htmlFor="model-max-input">
              <Input
                id="model-max-input"
                type="number"
                min={1}
                value={maxInput}
                onChange={(event) => setMaxInput(event.target.value)}
              />
            </Field>
            <Field label="최대 출력 토큰" htmlFor="model-max-output">
              <Input
                id="model-max-output"
                type="number"
                min={1}
                value={maxOutput}
                onChange={(event) => setMaxOutput(event.target.value)}
              />
            </Field>
          </div>

          <Field
            label="지원 방언"
            required
            error={fieldErrors['supported_dialects']}
            hint="client 는 모델과 무관하게 두 방언 중 하나를 고릅니다(ADR-0003)"
          >
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

          <Field label="설명" htmlFor="model-description">
            <Textarea
              id="model-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>

          <div className="border-t border-border pt-3">
            <p className="mb-2 text-xs font-medium">초기 단가</p>
            <PricingFields
              value={pricing}
              onChange={setPricing}
              fieldErrors={fieldErrors}
              idPrefix="model-create"
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
