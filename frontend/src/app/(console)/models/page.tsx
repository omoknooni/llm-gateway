import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { Select } from '@/components/ui/field';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { CreateModelDialog } from '@/components/models/create-model-dialog';
import { ModelRowActions } from '@/components/models/model-row-actions';
import { AdminApiError } from '@/lib/api/errors';
import { listModels, listModelsMissingPricing } from '@/lib/api/models';
import { requirePageAccess } from '@/lib/auth/session';
import { formatUsdPrice } from '@/lib/format/decimal';
import { DIALECT_LABEL, MODEL_STATUS_LABEL, MODEL_STATUS_TONE } from '@/lib/format/labels';
import { ModelStatus, UserRole } from '@/types/api';

export const metadata = { title: '모델 카탈로그 — llm-gateway Admin' };

export default async function ModelsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const session = await requirePageAccess('/models');
  const params = await searchParams;
  const isAdmin = session.role === UserRole.ADMIN;

  const status = params.status && params.status in ModelStatus
    ? (params.status as ModelStatus)
    : undefined;

  const [models, missingPricing] = await Promise.all([
    listModels(status),
    // 단가 목록은 ADMIN 전용입니다. 팀장에게는 이 카드가 보이지 않습니다.
    isAdmin
      ? listModelsMissingPricing().catch((error) => {
          if (error instanceof AdminApiError && error.isForbidden) return [];
          throw error;
        })
      : Promise.resolve([]),
  ]);

  return (
    <>
      <PageHeader
        title="모델 카탈로그"
        description="client 가 alias 로 호출하고, gateway 가 provider 모델 ID 로 옮깁니다."
        actions={isAdmin ? <CreateModelDialog /> : null}
      />

      {missingPricing.length > 0 ? (
        <Card className="mb-4 border-warning/40">
          <CardHeader
            title="단가가 없는 모델"
            description="사용량이 비용으로 환산되지 않습니다. 단가를 등록하세요."
          />
          <CardBody>
            <div className="flex flex-wrap gap-1.5">
              {missingPricing.map((alias) => (
                <Link key={alias} href={`/models/${alias}`}>
                  <Badge tone="warning" className="font-mono">
                    {alias}
                  </Badge>
                </Link>
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <form method="GET" className="mb-3 flex items-end gap-2">
        <label className="text-xs text-muted-foreground">
          상태
          <Select name="status" defaultValue={params.status ?? ''} className="mt-1 w-40">
            <option value="">전체</option>
            {Object.values(ModelStatus).map((value) => (
              <option key={value} value={value}>
                {MODEL_STATUS_LABEL[value]}
              </option>
            ))}
          </Select>
        </label>
        <Button type="submit">적용</Button>
      </form>

      <Card>
        <Table>
          <THead>
            <Tr>
              <Th>alias</Th>
              <Th>provider 모델 ID</Th>
              <Th>방언</Th>
              <Th>상태</Th>
              <Th numeric>입력 1K</Th>
              <Th numeric>출력 1K</Th>
              {isAdmin ? <Th numeric>동작</Th> : null}
            </Tr>
          </THead>
          <TBody>
            {models.length === 0 ? (
              <TEmpty colSpan={isAdmin ? 7 : 6}>등록된 모델이 없습니다.</TEmpty>
            ) : (
              models.map((model) => (
                <Tr key={model.alias}>
                  <Td className="font-medium">
                    <Link href={`/models/${model.alias}`} className="hover:underline">
                      <code className="font-mono text-xs">{model.alias}</code>
                    </Link>
                    {model.display_name ? (
                      <div className="text-xs text-muted-foreground">{model.display_name}</div>
                    ) : null}
                  </Td>
                  <Td className="text-muted-foreground">
                    <code className="font-mono text-xs break-all">{model.provider_model_id}</code>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {model.supported_dialects.map((dialect) => (
                        <Badge key={dialect} tone="neutral">
                          {DIALECT_LABEL[dialect]}
                        </Badge>
                      ))}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone={MODEL_STATUS_TONE[model.status]}>
                      {MODEL_STATUS_LABEL[model.status]}
                    </Badge>
                  </Td>
                  <Td numeric>
                    {model.current_pricing ? (
                      formatUsdPrice(model.current_pricing.input_price_per_1k)
                    ) : (
                      <span className="text-warning">미등록</span>
                    )}
                  </Td>
                  <Td numeric>
                    {model.current_pricing ? (
                      formatUsdPrice(model.current_pricing.output_price_per_1k)
                    ) : (
                      <span className="text-warning">미등록</span>
                    )}
                  </Td>
                  {isAdmin ? (
                    <Td numeric>
                      <ModelRowActions model={model} />
                    </Td>
                  ) : null}
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>
    </>
  );
}
