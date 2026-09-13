import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { Select } from '@/components/ui/field';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { getBudgetSummary, listUnsetBudgets } from '@/lib/api/budgets';
import { AdminApiError } from '@/lib/api/errors';
import { requirePageAccess } from '@/lib/auth/session';
import { formatUsd } from '@/lib/format/decimal';
import {
  ALERT_LEVEL_LABEL,
  ALERT_LEVEL_TONE,
  BUDGET_POLICY_LABEL,
  usageSourceLabel,
} from '@/lib/format/labels';
import { normalizePeriod, recentPeriods } from '@/lib/format/usage';
import { AlertLevel, BudgetScope, UserRole, type UnsetBudgetResponse } from '@/types/api';

export const metadata = { title: '예산 — llm-gateway Admin' };

const EMPTY_UNSET: UnsetBudgetResponse = { teams: [], users: [] };

/**
 * 예산 소진 현황.
 *
 * 두 가지를 한 화면에서 봅니다. **한도가 있는 대상의 소진율**과 **한도가 아예 없는 대상**.
 * 뒤쪽이 더 위험합니다 — 미설정은 무제한이라 아무 경보도 뜨지 않기 때문입니다(backend 05 문서).
 *
 * 소진값의 출처(Redis 집행 카운터 / DB 집계)를 숨기지 않습니다. 둘이 갈라진 상태를 알아야
 * 재시드가 필요한지 판단할 수 있습니다.
 */
export default async function BudgetsPage({
  searchParams,
}: {
  searchParams: Promise<{ period?: string; scope?: string }>;
}) {
  const session = await requirePageAccess('/budgets');
  const params = await searchParams;
  const isAdmin = session.role === UserRole.ADMIN;

  const period = normalizePeriod(params.period);
  const scope = params.scope === BudgetScope.USER ? BudgetScope.USER : BudgetScope.TEAM;

  const [summary, unset] = await Promise.all([
    getBudgetSummary({ scope, period }),
    // 미설정 목록은 ADMIN 전용입니다. 팀장에게는 이 카드가 없습니다.
    isAdmin
      ? listUnsetBudgets().catch((error) => {
          if (error instanceof AdminApiError && error.isForbidden) return EMPTY_UNSET;
          throw error;
        })
      : Promise.resolve(EMPTY_UNSET),
  ]);

  const alerting = summary.items.filter((item) => item.alert_level !== AlertLevel.NORMAL);

  return (
    <>
      <PageHeader
        title="예산"
        description={`${period} (UTC 월 기준). 집행은 gateway 가 하고, 이 화면은 정책과 소진을 봅니다.`}
        actions={<Badge tone="neutral">소진값 출처 · {usageSourceLabel(summary.source)}</Badge>}
      />

      <form method="GET" className="mb-3 flex flex-wrap items-end gap-2">
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
        <label className="text-xs text-muted-foreground">
          대상
          <Select name="scope" defaultValue={scope} className="mt-1 w-32">
            <option value={BudgetScope.TEAM}>팀</option>
            <option value={BudgetScope.USER}>사용자</option>
          </Select>
        </label>
        <Button type="submit">적용</Button>
      </form>

      {alerting.length > 0 ? (
        <Card className="mb-4 border-warning/40">
          <CardHeader
            title="경보 중인 대상"
            description="임계는 각 예산의 설정값이고, 단계 계산은 backend 가 합니다."
          />
          <CardBody>
            <div className="flex flex-wrap gap-1.5">
              {alerting.map((item) => (
                <Badge key={item.scope_id} tone={ALERT_LEVEL_TONE[item.alert_level]}>
                  {item.name ?? item.scope_id} · {item.usage_pct}%
                </Badge>
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title={scope === BudgetScope.TEAM ? '팀 예산' : '사용자 예산'}
          description="여기 없는 대상은 예산이 설정되지 않은 것이고, 곧 무제한입니다."
        />
        <Table>
          <THead>
            <Tr>
              <Th>대상</Th>
              <Th numeric>한도</Th>
              <Th numeric>소진</Th>
              <Th numeric>남은 금액</Th>
              <Th numeric>소진율</Th>
              <Th>정책</Th>
              <Th>경보</Th>
              <Th>출처</Th>
            </Tr>
          </THead>
          <TBody>
            {summary.items.length === 0 ? (
              <TEmpty colSpan={8}>설정된 예산이 없습니다.</TEmpty>
            ) : (
              summary.items.map((item) => (
                <Tr key={`${item.scope}:${item.scope_id}`}>
                  <Td className="font-medium">
                    {item.scope === BudgetScope.TEAM ? (
                      <Link href={`/budgets/team/${item.scope_id}`} className="hover:underline">
                        {item.name ?? item.scope_id}
                      </Link>
                    ) : (
                      (item.name ?? <code className="font-mono text-xs">{item.scope_id}</code>)
                    )}
                  </Td>
                  <Td numeric>{formatUsd(item.limit_usd)}</Td>
                  <Td numeric>{formatUsd(item.used_usd)}</Td>
                  <Td numeric>{formatUsd(item.remaining_usd)}</Td>
                  <Td numeric>{item.usage_pct}%</Td>
                  <Td className="text-muted-foreground">{BUDGET_POLICY_LABEL[item.policy]}</Td>
                  <Td>
                    <Badge tone={ALERT_LEVEL_TONE[item.alert_level]}>
                      {ALERT_LEVEL_LABEL[item.alert_level]}
                    </Badge>
                  </Td>
                  <Td className="text-xs text-muted-foreground">{usageSourceLabel(item.source)}</Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      {isAdmin ? (
        <Card className={`mt-4 ${unset.teams.length > 0 ? 'border-danger/35' : ''}`}>
          <CardHeader
            title="예산이 없는 대상"
            description="미설정은 차단하지 않습니다. 상시 노출이 유일한 방어선입니다."
          />
          <CardBody className="space-y-3">
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">팀 {unset.teams.length}개</p>
              {unset.teams.length === 0 ? (
                <p className="text-sm text-muted-foreground">모든 팀에 예산이 있습니다.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {unset.teams.map((team) => (
                    <Link key={team.id} href={`/budgets/team/${team.id}`}>
                      <Badge tone="danger">{team.name}</Badge>
                    </Link>
                  ))}
                </div>
              )}
            </div>
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">사용자 {unset.users.length}명</p>
              {unset.users.length === 0 ? (
                <p className="text-sm text-muted-foreground">모든 사용자에게 배분이 있습니다.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {unset.users.map((user) => (
                    <Badge key={user.id} tone="warning">
                      {user.name}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </CardBody>
        </Card>
      ) : null}
    </>
  );
}
