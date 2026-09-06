'use server';

import { revalidatePath } from 'next/cache';
import { z } from 'zod';

import { createModel, createPricing, setModelStatus, updateModel } from '@/lib/api/models';
import type {
  ApiDialect,
  ModelResponse,
  ModelStatus,
  PricingResponse,
} from '@/types/api';

import { actionFailure, actionFieldErrors, actionOk, type ActionResult } from './types';

/** alias 규칙은 backend 의 path 파라미터 패턴과 같습니다. 먼저 걸러 422 왕복을 줄입니다. */
const ALIAS_PATTERN = /^[a-z0-9][a-z0-9.-]{1,127}$/;

/** 금액은 문자열입니다. 숫자로 파싱하지 않고 형식만 검사합니다(정밀도 유지). */
const DECIMAL_PATTERN = /^\d+(\.\d+)?$/;

const createSchema = z.object({
  alias: z
    .string()
    .trim()
    .regex(ALIAS_PATTERN, '소문자·숫자로 시작하고 소문자·숫자·점·하이픈만 쓸 수 있습니다'),
  provider_model_id: z.string().trim().min(1, 'provider 모델 ID 를 입력하세요'),
});

function validatePricing(input: {
  input_price_per_1k: string;
  output_price_per_1k: string;
  cache_write_price_per_1k: string;
  cache_read_price_per_1k: string;
  effective_from: string;
}): Record<string, string> {
  const errors: Record<string, string> = {};
  const decimals = {
    input_price_per_1k: input.input_price_per_1k,
    output_price_per_1k: input.output_price_per_1k,
    cache_write_price_per_1k: input.cache_write_price_per_1k,
    cache_read_price_per_1k: input.cache_read_price_per_1k,
  };
  for (const [field, value] of Object.entries(decimals)) {
    if (!DECIMAL_PATTERN.test(value.trim())) {
      errors[field] = '0 이상의 숫자를 소수점 형태로 입력하세요';
    }
  }
  if (!input.effective_from) {
    errors['effective_from'] = '적용 시작 시각을 지정하세요';
  }
  return errors;
}

export async function createModelAction(input: {
  alias: string;
  display_name: string;
  provider_model_id: string;
  region: string;
  supported_dialects: ApiDialect[];
  max_input_tokens: string;
  max_output_tokens: string;
  supports_streaming: boolean;
  description: string;
  pricing: {
    input_price_per_1k: string;
    output_price_per_1k: string;
    cache_write_price_per_1k: string;
    cache_read_price_per_1k: string;
    effective_from: string;
  };
}): Promise<ActionResult<ModelResponse>> {
  const parsed = createSchema.safeParse(input);
  const fieldErrors: Record<string, string> = {};
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const key = issue.path[0];
      if (typeof key === 'string' && !(key in fieldErrors)) fieldErrors[key] = issue.message;
    }
  }
  if (input.supported_dialects.length === 0) {
    fieldErrors['supported_dialects'] = '최소 한 개의 방언을 선택하세요';
  }
  Object.assign(fieldErrors, validatePricing(input.pricing));
  if (Object.keys(fieldErrors).length > 0) return actionFieldErrors(fieldErrors);

  try {
    const model = await createModel({
      alias: input.alias.trim(),
      display_name: input.display_name.trim() || null,
      provider_model_id: input.provider_model_id.trim(),
      region: input.region.trim() || null,
      supported_dialects: input.supported_dialects,
      max_input_tokens: input.max_input_tokens ? Number(input.max_input_tokens) : null,
      max_output_tokens: input.max_output_tokens ? Number(input.max_output_tokens) : null,
      supports_streaming: input.supports_streaming,
      description: input.description.trim() || null,
      pricing: {
        input_price_per_1k: input.pricing.input_price_per_1k.trim(),
        output_price_per_1k: input.pricing.output_price_per_1k.trim(),
        cache_write_price_per_1k: input.pricing.cache_write_price_per_1k.trim(),
        cache_read_price_per_1k: input.pricing.cache_read_price_per_1k.trim(),
        effective_from: input.pricing.effective_from,
      },
    });
    revalidatePath('/models');
    return actionOk(model);
  } catch (error) {
    return actionFailure(error);
  }
}

export async function updateModelAction(
  alias: string,
  input: {
    display_name?: string;
    provider_model_id?: string;
    region?: string;
    supported_dialects?: ApiDialect[];
    max_input_tokens?: string;
    max_output_tokens?: string;
    supports_streaming?: boolean;
    description?: string;
  },
): Promise<ActionResult<ModelResponse>> {
  if (input.supported_dialects && input.supported_dialects.length === 0) {
    return actionFieldErrors({ supported_dialects: '최소 한 개의 방언을 선택하세요' });
  }

  try {
    const model = await updateModel(alias, {
      ...(input.display_name === undefined ? {} : { display_name: input.display_name.trim() || null }),
      ...(input.provider_model_id === undefined
        ? {}
        : { provider_model_id: input.provider_model_id.trim() }),
      ...(input.region === undefined ? {} : { region: input.region.trim() || null }),
      ...(input.supported_dialects === undefined
        ? {}
        : { supported_dialects: input.supported_dialects }),
      ...(input.max_input_tokens === undefined
        ? {}
        : { max_input_tokens: input.max_input_tokens ? Number(input.max_input_tokens) : null }),
      ...(input.max_output_tokens === undefined
        ? {}
        : { max_output_tokens: input.max_output_tokens ? Number(input.max_output_tokens) : null }),
      ...(input.supports_streaming === undefined
        ? {}
        : { supports_streaming: input.supports_streaming }),
      ...(input.description === undefined ? {} : { description: input.description.trim() || null }),
    });
    revalidatePath('/models');
    revalidatePath(`/models/${alias}`);
    return actionOk(model);
  } catch (error) {
    return actionFailure(error);
  }
}

/**
 * 상태 전환.
 *
 * 비활성화하면 gateway 의 `policy:model:{alias}` 캐시가 지워지고, 이 모델을 쓰던 호출이
 * 거절되기 시작합니다. 카탈로그에서 지우는 것이 아니라 **끄는** 조작입니다.
 */
export async function setModelStatusAction(
  alias: string,
  status: ModelStatus,
): Promise<ActionResult<ModelResponse>> {
  try {
    const model = await setModelStatus(alias, { status });
    revalidatePath('/models');
    revalidatePath(`/models/${alias}`);
    return actionOk(model);
  } catch (error) {
    return actionFailure(error);
  }
}

/** 단가 등록. 구간이 겹치면 backend 가 409 로 막고, 화면은 그 메시지를 그대로 보여줍니다. */
export async function createPricingAction(
  alias: string,
  input: {
    input_price_per_1k: string;
    output_price_per_1k: string;
    cache_write_price_per_1k: string;
    cache_read_price_per_1k: string;
    effective_from: string;
  },
): Promise<ActionResult<PricingResponse>> {
  const fieldErrors = validatePricing(input);
  if (Object.keys(fieldErrors).length > 0) return actionFieldErrors(fieldErrors);

  try {
    const pricing = await createPricing(alias, {
      input_price_per_1k: input.input_price_per_1k.trim(),
      output_price_per_1k: input.output_price_per_1k.trim(),
      cache_write_price_per_1k: input.cache_write_price_per_1k.trim(),
      cache_read_price_per_1k: input.cache_read_price_per_1k.trim(),
      effective_from: input.effective_from,
    });
    revalidatePath('/models');
    revalidatePath(`/models/${alias}`);
    return actionOk(pricing);
  } catch (error) {
    return actionFailure(error);
  }
}
