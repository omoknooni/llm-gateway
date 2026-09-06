import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { StatCard } from '@/components/ui/stat-card';
import { AdminApiError } from '@/lib/api/errors';
import { listModelsMissingPricing } from '@/lib/api/models';
import { listTeams } from '@/lib/api/teams';
import { listUsers } from '@/lib/api/users';
import { listVirtualKeys } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { isoDaysFromNow } from '@/lib/format/datetime';
import { UserRole, VKStatus, type Page } from '@/types/api';

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

/** 목록 API 에 전체 건수가 없습니다. 표시 상한까지 세고, 더 있으면 `+` 를 붙입니다. */
const COUNT_LIMIT = 200;

function countOf(page: Page<unknown>): string {
  return page.has_more ? `${page.items.length}+` : String(page.items.length);
}

export default async function DashboardPage() {
  const session = await requirePageAccess('/');
  const isAdmin = session.role === UserRole.ADMIN;

  const [teams, users, activeKeys, expiringKeys, idleKeys, missingPricing] = await Promise.all([
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
  ]);

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
          title="아직 열리지 않은 화면"
          description="backend 마일스톤이 열리면 이어서 붙습니다."
        />
        <CardBody>
          <ul className="space-y-1.5 text-sm text-muted-foreground">
            <li>· 예산 설정과 소진 현황 — backend M6</li>
            <li>· 사용량·비용 대시보드와 리더보드 — backend M7</li>
            <li>· rate limit 설정과 실시간 사용률 — backend M8</li>
          </ul>
          {isAdmin ? (
            <div className="mt-3">
              <Button variant="secondary" size="sm" asChild>
                <Link href="/settings/cache">캐시 무효화 잔량 확인</Link>
              </Button>
            </div>
          ) : null}
        </CardBody>
      </Card>
    </>
  );
}
