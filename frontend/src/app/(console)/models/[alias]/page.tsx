import Link from 'next/link';
import { notFound } from 'next/navigation';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardBody,
  CardHeader,
  DescriptionItem,
  DescriptionList,
  PageHeader,
} from '@/components/ui/card';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { AddPricingDialog } from '@/components/models/add-pricing-dialog';
import { ModelRowActions } from '@/components/models/model-row-actions';
import { AdminApiError } from '@/lib/api/errors';
import { getModel, listPricings } from '@/lib/api/models';
import { requirePageAccess } from '@/lib/auth/session';
import { formatDateTime } from '@/lib/format/datetime';
import { formatUsdPrice } from '@/lib/format/decimal';
import { DIALECT_LABEL, MODEL_STATUS_LABEL, MODEL_STATUS_TONE } from '@/lib/format/labels';
import { UserRole } from '@/types/api';

export const metadata = { title: '모델 상세 — llm-gateway Admin' };

export default async function ModelDetailPage({
  params,
}: {
  params: Promise<{ alias: string }>;
}) {
  const session = await requirePageAccess('/models');
  const { alias } = await params;
  const isAdmin = session.role === UserRole.ADMIN;

  let model;
  try {
    model = await getModel(alias);
  } catch (error) {
    if (error instanceof AdminApiError && error.isNotFound) notFound();
    throw error;
  }

  // 단가 이력은 ADMIN 전용입니다(backend 인가 표: 모델 단가는 ADMIN 만).
  const pricings = isAdmin ? await listPricings(alias) : [];

  return (
    <>
      <PageHeader
        title={<code className="font-mono">{model.alias}</code>}
        description={model.display_name ?? model.description ?? '설명이 없습니다.'}
        actions={
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/models">목록으로</Link>
            </Button>
            {isAdmin ? <ModelRowActions model={model} /> : null}
          </>
        }
      />

      <div className="space-y-4">
        <Card>
          <CardHeader title="기본 정보" />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="상태">
                <Badge tone={MODEL_STATUS_TONE[model.status]}>
                  {MODEL_STATUS_LABEL[model.status]}
                </Badge>
              </DescriptionItem>
              <DescriptionItem term="provider">
                {model.provider} ·{' '}
                <code className="font-mono text-xs break-all">{model.provider_model_id}</code>
              </DescriptionItem>
              <DescriptionItem term="리전">
                {model.region ?? <span className="text-muted-foreground">배포 기본값</span>}
              </DescriptionItem>
              <DescriptionItem term="지원 방언">
                <div className="flex flex-wrap gap-1">
                  {model.supported_dialects.map((dialect) => (
                    <Badge key={dialect} tone="neutral">
                      {DIALECT_LABEL[dialect]}
                    </Badge>
                  ))}
                </div>
              </DescriptionItem>
              <DescriptionItem term="토큰 한도">
                입력 {model.max_input_tokens?.toLocaleString() ?? '—'} / 출력{' '}
                {model.max_output_tokens?.toLocaleString() ?? '—'}
              </DescriptionItem>
              <DescriptionItem term="스트리밍">
                {model.supports_streaming ? '지원' : '미지원'}
              </DescriptionItem>
            </DescriptionList>
          </CardBody>
        </Card>

        {isAdmin ? (
          <Card>
            <CardHeader
              title="단가 이력"
              description="금액은 문자열 그대로 다룹니다. 구간이 겹치는 등록은 거절됩니다."
              actions={<AddPricingDialog alias={model.alias} />}
            />
            <Table>
              <THead>
                <Tr>
                  <Th>적용 구간</Th>
                  <Th numeric>입력 1K</Th>
                  <Th numeric>출력 1K</Th>
                  <Th numeric>캐시 쓰기</Th>
                  <Th numeric>캐시 읽기</Th>
                  <Th>출처</Th>
                </Tr>
              </THead>
              <TBody>
                {pricings.length === 0 ? (
                  <TEmpty colSpan={6}>
                    등록된 단가가 없습니다. 이 모델의 사용량은 비용으로 환산되지 않습니다.
                  </TEmpty>
                ) : (
                  pricings.map((pricing) => {
                    const current = pricing.effective_until === null;
                    return (
                      <Tr key={pricing.id}>
                        <Td>
                          {formatDateTime(pricing.effective_from)} ~{' '}
                          {pricing.effective_until
                            ? formatDateTime(pricing.effective_until)
                            : '현재'}
                          {current ? (
                            <Badge tone="success" className="ml-2">
                              적용 중
                            </Badge>
                          ) : null}
                        </Td>
                        <Td numeric>{formatUsdPrice(pricing.input_price_per_1k, pricing.currency)}</Td>
                        <Td numeric>
                          {formatUsdPrice(pricing.output_price_per_1k, pricing.currency)}
                        </Td>
                        <Td numeric>
                          {formatUsdPrice(pricing.cache_write_price_per_1k, pricing.currency)}
                        </Td>
                        <Td numeric>
                          {formatUsdPrice(pricing.cache_read_price_per_1k, pricing.currency)}
                        </Td>
                        <Td className="text-muted-foreground">{pricing.source}</Td>
                      </Tr>
                    );
                  })
                )}
              </TBody>
            </Table>
          </Card>
        ) : null}
      </div>
    </>
  );
}
