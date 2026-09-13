import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/field';
import { StatCard } from '@/components/ui/stat-card';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { TrendChart } from '@/components/usage/trend-chart';
import {
  getAuthEventSummary,
  getUsageLeaderboard,
  getUsageOverview,
  getUsageTrend,
  type UsageQuery,
} from '@/lib/api/usage';
import { requirePageAccess } from '@/lib/auth/session';
import { formatUsd } from '@/lib/format/decimal';
import {
  TREND_GRANULARITY_LABEL,
  USAGE_AXIS_LABEL,
  USAGE_METRIC_LABEL,
  authOutcomeLabel,
} from '@/lib/format/labels';
import {
  fillTrend,
  formatCount,
  formatLatency,
  formatPercent,
  normalizeRange,
  rangeDays,
} from '@/lib/format/usage';
import {
  TrendGranularity,
  UsageAxis,
  UsageMetric,
  type LeaderboardEntry,
} from '@/types/api';

export const metadata = { title: '사용량·비용 — llm-gateway Admin' };

/**
 * 사용량·비용과 리더보드.
 *
 * drill-down 은 별도 화면이 아니라 **같은 화면에 필터를 더하는 것**입니다(backend 10 문서).
 * 리더보드 행이 자기 축의 필터를 URL 에 붙이고, 그러면 위의 합계·추이까지 같은 조건으로
 * 좁혀집니다. 숫자가 서로 다른 기준에서 나오는 일이 없습니다.
 *
 * 인가 범위 축소는 backend 몫입니다. 팀장이 다른 팀을 지정하면 빈 결과가 아니라 403 이고,
 * 화면은 그 403 을 그대로 드러냅니다 — "데이터 없음"으로 덮으면 권한과 빈 데이터를
 * 구분할 수 없습니다.
 */
type SearchParams = Promise<Record<string, string | undefined>>;

function pickEnum<T extends Record<string, string>>(
  values: T,
  raw: string | undefined,
  fallback: T[keyof T],
): T[keyof T] {
  return raw && raw in values ? (raw as T[keyof T]) : fallback;
}

/** 리더보드 행에서 자기 축으로 좁히는 링크. 이미 걸린 필터는 유지합니다. */
function drillDownHref(
  params: Record<string, string | undefined>,
  axis: UsageAxis,
  key: string,
): string {
  const next = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value) as [string, string][],
  );
  const field = {
    [UsageAxis.TEAM]: 'team_id',
    [UsageAxis.USER]: 'user_id',
    [UsageAxis.MODEL]: 'model_alias',
    [UsageAxis.VIRTUAL_KEY]: 'virtual_key_id',
  }[axis];
  next.set(field, key);
  return `/usage?${next.toString()}`;
}

export default async function UsagePage({ searchParams }: { searchParams: SearchParams }) {
  await requirePageAccess('/usage');
  const params = await searchParams;

  const range = normalizeRange(params['from_date'], params['to_date']);
  const axis = pickEnum(UsageAxis, params['axis'], UsageAxis.TEAM);
  const metric = pickEnum(UsageMetric, params['metric'], UsageMetric.COST);
  const granularity = pickEnum(TrendGranularity, params['granularity'], TrendGranularity.DAY);

  const filters: UsageQuery = {
    from_date: range.from,
    to_date: range.to,
    team_id: params['team_id'],
    user_id: params['user_id'],
    virtual_key_id: params['virtual_key_id'],
    model_alias: params['model_alias'],
  };

  const [overview, leaderboard, trend, authEvents] = await Promise.all([
    getUsageOverview(filters),
    getUsageLeaderboard({ ...filters, axis, metric, limit: 20 }),
    getUsageTrend({ ...filters, granularity }),
    getAuthEventSummary(filters),
  ]);

  const totals = overview.totals;
  const buckets = fillTrend(trend.points, range, granularity);
  const activeFilters = (['team_id', 'user_id', 'virtual_key_id', 'model_alias'] as const).filter(
    (key) => filters[key],
  );

  return (
    <>
      <PageHeader
        title="사용량·비용"
        description={`${range.from} ~ ${range.to} (UTC, 양끝 포함 ${rangeDays(range)}일)`}
      />

      <form method="GET" className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-muted-foreground">
          시작
          <Input type="date" name="from_date" defaultValue={range.from} className="mt-1 w-40" />
        </label>
        <label className="text-xs text-muted-foreground">
          종료
          <Input type="date" name="to_date" defaultValue={range.to} className="mt-1 w-40" />
        </label>
        <label className="text-xs text-muted-foreground">
          모델
          <Input
            name="model_alias"
            defaultValue={params['model_alias'] ?? ''}
            placeholder="alias"
            className="mt-1 w-44 font-mono"
          />
        </label>
        <label className="text-xs text-muted-foreground">
          추이 단위
          <Select name="granularity" defaultValue={granularity} className="mt-1 w-28">
            {Object.values(TrendGranularity).map((value) => (
              <option key={value} value={value}>
                {TREND_GRANULARITY_LABEL[value]}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          정렬 지표
          <Select name="metric" defaultValue={metric} className="mt-1 w-32">
            {Object.values(UsageMetric).map((value) => (
              <option key={value} value={value}>
                {USAGE_METRIC_LABEL[value]}
              </option>
            ))}
          </Select>
        </label>
        <input type="hidden" name="axis" value={axis} />
        {/* 축을 벗어난 drill-down 필터는 폼 제출에도 유지합니다. */}
        {filters.team_id ? <input type="hidden" name="team_id" value={filters.team_id} /> : null}
        {filters.user_id ? <input type="hidden" name="user_id" value={filters.user_id} /> : null}
        {filters.virtual_key_id ? (
          <input type="hidden" name="virtual_key_id" value={filters.virtual_key_id} />
        ) : null}
        <Button type="submit">적용</Button>
      </form>

      {activeFilters.length > 0 ? (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">적용된 범위</span>
          {activeFilters.map((key) => (
            <Badge key={key} tone="info" className="font-mono">
              {key}={filters[key]}
            </Badge>
          ))}
          <Link
            href={`/usage?from_date=${range.from}&to_date=${range.to}`}
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            해제
          </Link>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="추정 비용" value={formatUsd(totals.estimated_cost_usd)} hint="기록 시점 단가" />
        <StatCard label="호출 수" value={formatCount(totals.request_count)} />
        <StatCard
          label="실패율"
          value={formatPercent(totals.failure_rate_pct)}
          hint={`실패 ${formatCount(totals.error_count)}건 (TIMEOUT 포함)`}
          tone={Number(totals.failure_rate_pct) >= 5 ? 'danger' : 'neutral'}
        />
        <StatCard
          label="토큰"
          value={formatCount(totals.total_tokens)}
          hint={`입력 ${formatCount(totals.input_tokens)} / 출력 ${formatCount(totals.output_tokens)}`}
        />
        <StatCard label="평균 지연" value={formatLatency(totals.avg_latency_ms)} hint="호출 수 가중" />
      </div>

      <Card className="mt-4">
        <CardHeader
          title={`${TREND_GRANULARITY_LABEL[granularity]}별 ${USAGE_METRIC_LABEL[metric]} 추이`}
          description="점선 구간은 집계가 없는 버킷입니다. 호출이 0 이던 날과 다릅니다."
        />
        <CardBody>
          <TrendChart buckets={buckets} metric={metric} />
        </CardBody>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title="리더보드"
          description="행을 누르면 그 대상으로 이 화면 전체가 좁혀집니다."
          actions={
            <div className="flex gap-1">
              {Object.values(UsageAxis).map((value) => {
                const next = new URLSearchParams(
                  Object.entries(params).filter(([, item]) => item) as [string, string][],
                );
                next.set('axis', value);
                return (
                  <Button
                    key={value}
                    size="sm"
                    variant={value === axis ? 'primary' : 'ghost'}
                    asChild
                  >
                    <Link href={`/usage?${next.toString()}`}>{USAGE_AXIS_LABEL[value]}</Link>
                  </Button>
                );
              })}
            </div>
          }
        />
        <Table>
          <THead>
            <Tr>
              <Th>{USAGE_AXIS_LABEL[axis]}</Th>
              <Th numeric>비용</Th>
              <Th numeric>호출</Th>
              <Th numeric>토큰</Th>
              <Th numeric>실패율</Th>
              <Th numeric>평균 지연</Th>
            </Tr>
          </THead>
          <TBody>
            {leaderboard.items.length === 0 ? (
              <TEmpty colSpan={6}>이 기간에 집계된 사용량이 없습니다.</TEmpty>
            ) : (
              leaderboard.items.map((entry: LeaderboardEntry) => (
                <Tr key={entry.key}>
                  <Td className="font-medium">
                    <Link
                      href={drillDownHref(params, axis, entry.key)}
                      className="hover:underline"
                    >
                      {entry.name ?? <code className="font-mono text-xs">{entry.key}</code>}
                    </Link>
                  </Td>
                  <Td numeric>{formatUsd(entry.totals.estimated_cost_usd)}</Td>
                  <Td numeric>{formatCount(entry.totals.request_count)}</Td>
                  <Td numeric>{formatCount(entry.totals.total_tokens)}</Td>
                  <Td numeric>{formatPercent(entry.totals.failure_rate_pct)}</Td>
                  <Td numeric>{formatLatency(entry.totals.avg_latency_ms)}</Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      <Card className="mt-4">
        <CardHeader
          title="정책 거절"
          description="401·403·429 입니다. 실제 실패 수는 gateway 가 묶은 창을 펼친 값입니다."
          actions={
            <Badge tone={authEvents.total_occurrences > 0 ? 'warning' : 'neutral'}>
              총 {formatCount(authEvents.total_occurrences)}건
            </Badge>
          }
        />
        <Table>
          <THead>
            <Tr>
              <Th>사유</Th>
              <Th numeric>실패 수</Th>
              <Th numeric>기록 행 수</Th>
            </Tr>
          </THead>
          <TBody>
            {authEvents.items.length === 0 ? (
              <TEmpty colSpan={3}>이 기간에 정책 거절이 없습니다.</TEmpty>
            ) : (
              authEvents.items.map((item) => (
                <Tr key={item.outcome}>
                  <Td className="font-medium">{authOutcomeLabel(item.outcome)}</Td>
                  <Td numeric>{formatCount(item.occurrence_count)}</Td>
                  <Td numeric className="text-muted-foreground">
                    {formatCount(item.event_rows)}
                  </Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>
    </>
  );
}
