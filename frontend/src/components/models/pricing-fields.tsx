'use client';

import { Field, Input } from '@/components/ui/field';

export interface PricingFormValue {
  input_price_per_1k: string;
  output_price_per_1k: string;
  cache_write_price_per_1k: string;
  cache_read_price_per_1k: string;
  effective_from: string;
}

export function emptyPricing(effectiveFromLocal: string): PricingFormValue {
  return {
    input_price_per_1k: '',
    output_price_per_1k: '',
    cache_write_price_per_1k: '0',
    cache_read_price_per_1k: '0',
    effective_from: effectiveFromLocal,
  };
}

/**
 * 단가 입력.
 *
 * `type="number"` 를 쓰지 않습니다. 브라우저가 값을 부동소수점으로 정규화해
 * `0.0003` 같은 단가가 흔들릴 수 있습니다. 문자열로 받아 문자열로 보냅니다
 * (AGENTS.md 금액 규약).
 */
export function PricingFields({
  value,
  onChange,
  fieldErrors,
  idPrefix,
}: {
  value: PricingFormValue;
  onChange: (next: PricingFormValue) => void;
  fieldErrors: Record<string, string>;
  idPrefix: string;
}) {
  const set = (key: keyof PricingFormValue) => (event: React.ChangeEvent<HTMLInputElement>) =>
    onChange({ ...value, [key]: event.target.value });

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field
        label="입력 1K 토큰 단가 (USD)"
        htmlFor={`${idPrefix}-input-price`}
        required
        error={fieldErrors['input_price_per_1k']}
      >
        <Input
          id={`${idPrefix}-input-price`}
          inputMode="decimal"
          placeholder="0.003"
          value={value.input_price_per_1k}
          onChange={set('input_price_per_1k')}
        />
      </Field>
      <Field
        label="출력 1K 토큰 단가 (USD)"
        htmlFor={`${idPrefix}-output-price`}
        required
        error={fieldErrors['output_price_per_1k']}
      >
        <Input
          id={`${idPrefix}-output-price`}
          inputMode="decimal"
          placeholder="0.015"
          value={value.output_price_per_1k}
          onChange={set('output_price_per_1k')}
        />
      </Field>
      <Field
        label="캐시 쓰기 단가"
        htmlFor={`${idPrefix}-cache-write`}
        error={fieldErrors['cache_write_price_per_1k']}
      >
        <Input
          id={`${idPrefix}-cache-write`}
          inputMode="decimal"
          value={value.cache_write_price_per_1k}
          onChange={set('cache_write_price_per_1k')}
        />
      </Field>
      <Field
        label="캐시 읽기 단가"
        htmlFor={`${idPrefix}-cache-read`}
        error={fieldErrors['cache_read_price_per_1k']}
      >
        <Input
          id={`${idPrefix}-cache-read`}
          inputMode="decimal"
          value={value.cache_read_price_per_1k}
          onChange={set('cache_read_price_per_1k')}
        />
      </Field>
      <Field
        label="적용 시작"
        htmlFor={`${idPrefix}-effective-from`}
        required
        error={fieldErrors['effective_from']}
        hint="기존 단가 구간과 겹치면 등록이 거절됩니다"
        className="sm:col-span-2"
      >
        <Input
          id={`${idPrefix}-effective-from`}
          type="datetime-local"
          value={value.effective_from}
          onChange={set('effective_from')}
        />
      </Field>
    </div>
  );
}
