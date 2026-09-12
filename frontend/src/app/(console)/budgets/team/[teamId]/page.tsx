import Link from 'next/link';

import { AllocationEditor } from '@/components/budgets/allocation-editor';
import { BudgetFormDialog } from '@/components/budgets/budget-form-dialog';
import { ReseedDialog } from '@/components/budgets/reseed-dialog';
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
import { Select } from '@/components/ui/field';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { getAllocation, getTeamBudgetUsage } from '@/lib/api/budgets';
import { getTeam, listTeamMembers } from '@/lib/api/teams';
import { requirePageAccess } from '@/lib/auth/session';
import { formatUsd } from '@/lib/format/decimal';
import {
  ALERT_LEVEL_LABEL,
  ALERT_LEVEL_TONE,
  BUDGET_POLICY_LABEL,
  usageSourceLabel,
} from '@/lib/format/labels';
import { formatCount, isBudgetUnset, normalizePeriod, recentPeriods } from '@/lib/format/usage';
import { BudgetScope, UserRole, type UsageBreakdownItem } from '@/types/api';

export const metadata = { title: '팀 예산 — llm-gateway Admin' };

function BreakdownTable({
  rows,
  keyLabel,
  emptyText,
}: {
  rows: UsageBreakdownItem[];
  keyLabel: string;
  emptyText: string;
}) {
  return (
    <Table>
      <THead>
        <Tr>
          <Th>{keyLabel}</Th>
          <Th numeric>비용</Th>
          <Th numeric>호출</Th>
          <Th numeric>입력 토큰</Th>
          <Th numeric>출력 토큰</Th>
        </Tr>
      </THead>
      <TBody>
        {rows.length === 0 ? (
          <TEmpty colSpan={5}>{emptyText}</TEmpty>
        ) : (
          rows.map((row) => (
            <Tr key={row.key}>
              <Td className="font-medium">
                {row.name ?? <code className="font-mono text-xs">{row.key}</code>}
              </Td>
              <Td numeric>{formatUsd(row.cost_usd)}</Td>
              <Td numeric>{formatCount(row.request_count)}</Td>
              <Td numeric>{formatCount(row.input_tokens)}</Td>
              <Td numeric>{formatCount(row.output_tokens)}</Td>
            </Tr>
          ))
        )}
      </TBody>
    </Table>
  );
}

/**
 * 팀 예산 상세.
 *
 * 한도 설정은 ADMIN 이고, 팀장은 **그 안에서 배분만** 합니다(backend 05 문서 인가 표).
 * 팀장에게 한도 입력칸을 보여주고 403 을 받게 하지 않습니다.
 *
 * breakdown 은 월 집계 테이블에서 옵니다. 집계 job 이 아직 돌지 않았으면 비어 있고,
 * 그것은 "사용량이 없다"와 다릅니다 — 빈 상태 문구가 그 차이를 말합니다.
 */
export default async function TeamBudgetPage({
  params,
  searchParams,
}: {
  params: Promise<{ teamId: string }>;
  searchParams: Promise<{ period?: string }>;
}) {
  const session = await requirePageAccess('/budgets');
  const { teamId } = await params;
  const period = normalizePeriod((await searchParams).period);
  const isAdmin = session.role === UserRole.ADMIN;

  const [team, usage, allocation, members] = await Promise.all([
    getTeam(teamId),
    getTeamBudgetUsage(teamId, period),
    getAllocation(teamId, period),
    listTeamMembers(teamId),
  ]);

  const budget = usage.budget;
  const configured = !isBudgetUnset(budget);

  return (
    <>
      <PageHeader
        title={team.name}
        description={`${period} 예산과 소진 (UTC 월 기준)`}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/usage?team_id=${teamId}`}>사용량 보기</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/teams/${teamId}`}>팀 상세</Link>
            </Button>
          </div>
        }
      />

      <form method="GET" className="mb-3 flex items-end gap-2">
        <label className="text-xs text-muted-foreground">
          기간
          <Select name="period" defaultValue={period} className="mt-1 w-36">
            {recentPeriods(12).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </label>
        <Button type="submit">적용</Button>
      </form>

      <div className="space-y-4">
        <Card className={configured ? '' : 'border-danger/35'}>
          <CardHeader
            title="팀 예산"
            description={
              configured
                ? '한도 변경은 즉시 유효하고 당월 소진 누적에는 영향이 없습니다.'
                : '예산이 설정되지 않았습니다. 이 팀은 무제한으로 호출할 수 있습니다.'
            }
            actions={
              isAdmin ? (
                <div className="flex items-center gap-2">
                  <BudgetFormDialog
                    teamId={teamId}
                    teamName={team.name}
                    configured={configured}
                    {...(configured ? { currentLimit: budget.limit_usd, currentPolicy: budget.policy } : {})}
                  />
                  {configured ? (
                    <ReseedDialog
                      scope={BudgetScope.TEAM}
                      scopeId={teamId}
                      period={period}
                      currentUsed={budget.used_usd}
                      label={team.name}
                    />
                  ) : null}
                </div>
              ) : null
            }
          />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="한도">
                {configured ? formatUsd(budget.limit_usd) : '무제한 (미설정)'}
              </DescriptionItem>
              <DescriptionItem term="소진">
                <span className="num">{formatUsd(budget.used_usd)}</span>{' '}
                <span className="text-xs text-muted-foreground">
                  · {usageSourceLabel(budget.source)}
                </span>
              </DescriptionItem>
              <DescriptionItem term="남은 금액">
                {configured ? formatUsd(budget.remaining_usd) : '—'}
              </DescriptionItem>
              <DescriptionItem term="소진율">
                {configured ? (
                  <span className="flex items-center gap-2">
                    <span className="num">{budget.usage_pct}%</span>
                    <Badge tone={ALERT_LEVEL_TONE[budget.alert_level]}>
                      {ALERT_LEVEL_LABEL[budget.alert_level]}
                    </Badge>
                  </span>
                ) : (
                  '—'
                )}
              </DescriptionItem>
              <DescriptionItem term="초과 정책">
                {configured ? BUDGET_POLICY_LABEL[budget.policy] : '—'}
              </DescriptionItem>
              <DescriptionItem term="미배분 여유분">
                {configured ? formatUsd(allocation.unallocated_usd) : '—'}
              </DescriptionItem>
            </DescriptionList>
          </CardBody>
        </Card>

        <AllocationEditor
          teamId={teamId}
          teamLimit={allocation.team_limit_usd}
          budgetConfigured={configured}
          members={members.map((member) => ({
            user_id: member.id,
            display_name: member.display_name,
            email: member.email,
            is_active: member.is_active,
          }))}
          allocations={allocation.allocations}
        />

        <Card>
          <CardHeader
            title="멤버별 사용"
            description="월 집계에서 옵니다. 팀 공용 키 호출은 사람에 귀속되지 않아 별도 항목으로 모입니다."
          />
          <BreakdownTable
            rows={usage.by_member}
            keyLabel="멤버"
            emptyText="집계된 사용량이 없습니다. 집계 job 이 아직 돌지 않았을 수도 있습니다."
          />
        </Card>

        <Card>
          <CardHeader title="모델별 사용" />
          <BreakdownTable rows={usage.by_model} keyLabel="모델" emptyText="집계된 사용량이 없습니다." />
        </Card>
      </div>
    </>
  );
}
