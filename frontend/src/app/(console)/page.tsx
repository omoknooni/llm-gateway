import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { StatCard } from '@/components/ui/stat-card';
import { getBudgetSummary, listUnsetBudgets } from '@/lib/api/budgets';
import { AdminApiError } from '@/lib/api/errors';
import { listModelsMissingPricing } from '@/lib/api/models';
import { getAuthEventSummary, getUsageOverview } from '@/lib/api/usage';
import { listTeams } from '@/lib/api/teams';
import { listUsers } from '@/lib/api/users';
import { listVirtualKeys } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { isoDaysFromNow } from '@/lib/format/datetime';
import { formatUsd } from '@/lib/format/decimal';
import { ALERT_LEVEL_LABEL, ALERT_LEVEL_TONE } from '@/lib/format/labels';
import { defaultRange, formatCount, formatPercent } from '@/lib/format/usage';
import { AlertLevel, BudgetScope, UserRole, VKStatus, type Page } from '@/types/api';

export const metadata = { title: '대시보드 — llm-gateway Admin' };

/**
 * 운영 점검판.
 *
 * 사용량·비용 지표는 backend M7(사용량 집계) 이후입니다. 그전까지 빈 차트 자리를 만들어두지
 * 않고, **지금 있는 API 로 답할 수 있는 것만** 보여줍니다(01 문서).
 *
 * 카드의 초점은 "조용히 어긋나 있는 상태"입니다 — 만료가 임박한 키, 오래 안 쓰는 키,
 * 단가가 없는 모델. 이것들은 아무도 보지 않으면 장애나 비용 누락으로 돌아옵니다.
 */
const EXPIRING_WITHIN_DAYS = 30;
const IDLE_AFTER_DAYS = 90;

/**
 * 사용량·예산 카드는 backend M6~M8 이 열린 뒤 붙었습니다. 그래도 첫 화면의 초점은 그대로
 * **조용히 어긋나 있는 상태**입니다 — 비용 총액보다 실패율·예산 경보·미설정 예산이 먼저입니다.
 */

/** 목록 API 에 전체 건수가 없습니다. 표시 상한까지 세고, 더 있으면 `+` 를 붙입니다. */
const COUNT_LIMIT = 200;

function countOf(page: Page<unknown>): string {
  return page.has_more ? `${page.items.length}+` : String(page.items.length);
}

export default async function DashboardPage() {
  const session = await requirePageAccess('/');
  const isAdmin = session.role === UserRole.ADMIN;

  const range = defaultRange();

  const [
    teams,
    users,
    activeKeys,
    expiringKeys,
    idleKeys,
    missingPricing,
    overview,
    authEvents,
    budgets,
    unsetBudgets,
  ] = await Promise.all([
    listTeams({ limit: COUNT_LIMIT }),
    listUsers({ limit: COUNT_LIMIT, is_active: true }),
    listVirtualKeys({ status: VKStatus.ACTIVE, limit: COUNT_LIMIT }),
    listVirtualKeys({
      status: VKStatus.ACTIVE,
      expires_before: isoDaysFromNow(EXPIRING_WITHIN_DAYS),
      limit: COUNT_LIMIT,
    }),
    listVirtualKeys({
      status: VKStatus.ACTIVE,
      unused_since: isoDaysFromNow(-IDLE_AFTER_DAYS),
      limit: COUNT_LIMIT,
    }),
    isAdmin
      ? listModelsMissingPricing().catch((error) => {
          if (error instanceof AdminApiError && error.isForbidden) return [];
          throw error;
        })
      : Promise.resolve([]),
    getUsageOverview({ from_date: range.from, to_date: range.to }),
    getAuthEventSummary({ from_date: range.from, to_date: range.to }),
    // 팀에 소속되지 않은 팀장이면 backend 가 403 입니다. 카드 하나 때문에 첫 화면 전체가
    // 죽지 않게 여기서만 삼킵니다 — 예산 화면에서는 그대로 드러냅니다.
    getBudgetSummary({ scope: BudgetScope.TEAM }).catch((error) => {
      if (error instanceof AdminApiError && error.isForbidden) {
        return { period: '', source: '', items: [] };
      }
      throw error;
    }),
    isAdmin
      ? listUnsetBudgets().catch((error) => {
          if (error instanceof AdminApiError && error.isForbidden) return { teams: [], users: [] };
          throw error;
        })
      : Promise.resolve({ teams: [], users: [] }),
  ]);

  const alerting = budgets.items.filter((item) => item.alert_level !== AlertLevel.NORMAL);

  return (
    <>
      <PageHeader
        title="대시보드"
        description="정책이 조용히 어긋나 있는 지점을 먼저 보여줍니다."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard label="팀" value={countOf(teams)} href="/teams" />
        <StatCard label="활성 사용자" value={countOf(users)} href="/users" />
        <StatCard label="활성 Virtual Key" value={countOf(activeKeys)} href="/keys?status=ACTIVE" />
        <StatCard
          label={`${EXPIRING_WITHIN_DAYS}일 내 만료 예정 키`}
          value={countOf(expiringKeys)}
          hint="만료되면 해당 client 호출이 즉시 실패합니다"
          tone={expiringKeys.items.length > 0 ? 'warning' : 'neutral'}
          href="/keys?preset=expiring"
        />
        <StatCard
          label={`${IDLE_AFTER_DAYS}일 이상 미사용 키`}
          value={countOf(idleKeys)}
          hint="쓰지 않는 키는 공격 표면입니다"
          tone={idleKeys.items.length > 0 ? 'warning' : 'neutral'}
          href="/keys?preset=idle"
        />
        {isAdmin ? (
          <StatCard
            label="단가 없는 모델"
            value={String(missingPricing.length)}
            hint="사용량이 비용으로 환산되지 않습니다"
            tone={missingPricing.length > 0 ? 'danger' : 'neutral'}
            href="/models"
          />
        ) : null}
      </div>

      {isAdmin && missingPricing.length > 0 ? (
        <Card className="mt-4 border-danger/35">
          <CardHeader
            title="단가 등록이 필요한 모델"
            description="비용 집계가 시작되기 전에 채워야 합니다."
          />
          <CardBody>
            <div className="flex flex-wrap gap-1.5">
              {missingPricing.map((alias) => (
                <Link key={alias} href={`/models/${alias}`}>
                  <Badge tone="danger" className="font-mono">
                    {alias}
                  </Badge>
                </Link>
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card className="mt-4">
        <CardHeader
          title={`최근 ${EXPIRING_WITHIN_DAYS}일 사용량`}
          description={`${range.from} ~ ${range.to} (UTC)`}
          actions={
            <Button variant="ghost" size="sm" asChild>
              <Link href="/usage">자세히</Link>
            </Button>
          }
        />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="추정 비용" value={formatUsd(overview.totals.estimated_cost_usd)} />
            <StatCard label="호출 수" value={formatCount(overview.totals.request_count)} />
            <StatCard
              label="실패율"
              value={formatPercent(overview.totals.failure_rate_pct)}
              hint="TIMEOUT 도 실패입니다"
              tone={Number(overview.totals.failure_rate_pct) >= 5 ? 'danger' : 'neutral'}
            />
            <StatCard
              label="정책 거절"
              value={formatCount(authEvents.total_occurrences)}
              hint="401·403·429. 키·모델·예산·한도 설정을 의심하세요"
              tone={authEvents.total_occurrences > 0 ? 'warning' : 'neutral'}
              href="/usage"
            />
          </div>
        </CardBody>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className={alerting.length > 0 ? 'border-warning/40' : ''}>
          <CardHeader
            title="예산 경보"
            description="경보 단계는 각 예산의 임계값으로 backend 가 계산합니다."
            actions={
              <Button variant="ghost" size="sm" asChild>
                <Link href="/budgets">예산 화면</Link>
              </Button>
            }
          />
          <CardBody>
            {alerting.length === 0 ? (
              <p className="text-sm text-muted-foreground">경보 중인 팀 예산이 없습니다.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {alerting.map((item) => (
                  <Link key={item.scope_id} href={`/budgets/team/${item.scope_id}`}>
                    <Badge tone={ALERT_LEVEL_TONE[item.alert_level]}>
                      {item.name ?? item.scope_id} · {item.usage_pct}% ·{' '}
                      {ALERT_LEVEL_LABEL[item.alert_level]}
                    </Badge>
                  </Link>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        {isAdmin ? (
          <Card className={unsetBudgets.teams.length > 0 ? 'border-danger/35' : ''}>
            <CardHeader
              title="예산이 없는 팀"
              description="미설정은 무제한입니다. 경보가 뜨지 않으니 여기서만 보입니다."
            />
            <CardBody>
              {unsetBudgets.teams.length === 0 ? (
                <p className="text-sm text-muted-foreground">모든 팀에 예산이 있습니다.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {unsetBudgets.teams.map((team) => (
                    <Link key={team.id} href={`/budgets/team/${team.id}`}>
                      <Badge tone="danger">{team.name}</Badge>
                    </Link>
                  ))}
                </div>
              )}
              <div className="mt-3">
                <Button variant="secondary" size="sm" asChild>
                  <Link href="/settings/cache">캐시 무효화 잔량 확인</Link>
                </Button>
              </div>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </>
  );
}
