import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, PageHeader } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/field';
import { CursorPagination } from '@/components/ui/pagination';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { IssueKeyDialog } from '@/components/keys/issue-key-dialog';
import { KeyRowActions } from '@/components/keys/key-row-actions';
import { listModels } from '@/lib/api/models';
import { listTeams } from '@/lib/api/teams';
import { listUsers } from '@/lib/api/users';
import { listVirtualKeys } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { expiryHint, formatDateTime, isoDaysFromNow } from '@/lib/format/datetime';
import { VK_OWNER_TYPE_LABEL, VK_STATUS_LABEL, VK_STATUS_TONE } from '@/lib/format/labels';
import { VKOwnerType, VKStatus } from '@/types/api';

export const metadata = { title: 'Virtual Key — llm-gateway Admin' };

/** 만료 임박·유휴 판정 기준. 대시보드 카드와 같은 값을 씁니다. */
const EXPIRING_WITHIN_DAYS = 30;
const IDLE_AFTER_DAYS = 90;

interface SearchParams {
  owner_type?: string;
  owner_id?: string;
  team_id?: string;
  status?: string;
  q?: string;
  preset?: string;
  cursor?: string;
}

function asStatus(raw?: string): VKStatus | undefined {
  return raw && raw in VKStatus ? (raw as VKStatus) : undefined;
}

function asOwnerType(raw?: string): VKOwnerType | undefined {
  return raw && raw in VKOwnerType ? (raw as VKOwnerType) : undefined;
}

export default async function KeysPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  await requirePageAccess('/keys');
  const params = await searchParams;

  const preset = params.preset;
  const [page, teamsPage, usersPage, models] = await Promise.all([
    listVirtualKeys({
      owner_type: asOwnerType(params.owner_type),
      owner_id: params.owner_id || undefined,
      team_id: params.team_id || undefined,
      status: asStatus(params.status) ?? (preset ? VKStatus.ACTIVE : undefined),
      expires_before: preset === 'expiring' ? isoDaysFromNow(EXPIRING_WITHIN_DAYS) : undefined,
      unused_since: preset === 'idle' ? isoDaysFromNow(-IDLE_AFTER_DAYS) : undefined,
      q: params.q || undefined,
      cursor: params.cursor,
      limit: 50,
    }),
    listTeams({ limit: 200 }),
    listUsers({ limit: 200, is_active: true }),
    listModels(),
  ]);

  const teamName = new Map(teamsPage.items.map((team) => [team.id, team.name]));
  const userName = new Map(usersPage.items.map((user) => [user.id, user.display_name]));

  const ownerLabel = (ownerType: VKOwnerType, ownerId: string) =>
    (ownerType === VKOwnerType.TEAM ? teamName.get(ownerId) : userName.get(ownerId)) ??
    ownerId.slice(0, 8);

  return (
    <>
      <PageHeader
        title="Virtual Key"
        description="client 가 gateway 를 호출할 때 쓰는 자격 증명입니다. 실제 AWS 키는 노출되지 않습니다."
        actions={
          <IssueKeyDialog teams={teamsPage.items} users={usersPage.items} models={models} />
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button variant={preset === 'expiring' ? 'primary' : 'secondary'} size="sm" asChild>
          <Link href="/keys?preset=expiring">{EXPIRING_WITHIN_DAYS}일 내 만료</Link>
        </Button>
        <Button variant={preset === 'idle' ? 'primary' : 'secondary'} size="sm" asChild>
          <Link href="/keys?preset=idle">{IDLE_AFTER_DAYS}일 이상 미사용</Link>
        </Button>
        {preset ? (
          <Button variant="ghost" size="sm" asChild>
            <Link href="/keys">조건 해제</Link>
          </Button>
        ) : null}
      </div>

      <form method="GET" className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-xs text-muted-foreground">
          소유 주체
          <Select name="owner_type" defaultValue={params.owner_type ?? ''} className="mt-1 w-32">
            <option value="">전체</option>
            {Object.values(VKOwnerType).map((value) => (
              <option key={value} value={value}>
                {VK_OWNER_TYPE_LABEL[value]}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          팀
          <Select name="team_id" defaultValue={params.team_id ?? ''} className="mt-1 w-48">
            <option value="">전체</option>
            {teamsPage.items.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          상태
          <Select name="status" defaultValue={params.status ?? ''} className="mt-1 w-36">
            <option value="">전체</option>
            {Object.values(VKStatus).map((value) => (
              <option key={value} value={value}>
                {VK_STATUS_LABEL[value]}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          검색
          <Input
            name="q"
            defaultValue={params.q ?? ''}
            placeholder="이름 또는 prefix"
            className="mt-1 w-52"
          />
        </label>
        <Button type="submit">적용</Button>
        <Button variant="ghost" asChild>
          <Link href="/keys">초기화</Link>
        </Button>
      </form>

      <Card>
        <Table>
          <THead>
            <Tr>
              <Th>이름</Th>
              <Th>prefix</Th>
              <Th>소유</Th>
              <Th>상태</Th>
              <Th>만료</Th>
              <Th>마지막 사용</Th>
              <Th numeric>동작</Th>
            </Tr>
          </THead>
          <TBody>
            {page.items.length === 0 ? (
              <TEmpty colSpan={7}>조건에 맞는 Virtual Key 가 없습니다.</TEmpty>
            ) : (
              page.items.map((vkey) => (
                <Tr key={vkey.id}>
                  <Td className="font-medium">
                    <Link href={`/keys/${vkey.id}`} className="hover:underline">
                      {vkey.name}
                    </Link>
                  </Td>
                  <Td>
                    <code className="font-mono text-xs">{vkey.key_prefix}</code>
                  </Td>
                  <Td>
                    <span className="text-muted-foreground">
                      {VK_OWNER_TYPE_LABEL[vkey.owner_type]}
                    </span>{' '}
                    {ownerLabel(vkey.owner_type, vkey.owner_id)}
                  </Td>
                  <Td>
                    <Badge tone={VK_STATUS_TONE[vkey.status]}>
                      {VK_STATUS_LABEL[vkey.status]}
                    </Badge>
                  </Td>
                  <Td>
                    <div className="text-muted-foreground">{formatDateTime(vkey.expires_at)}</div>
                    {vkey.status === VKStatus.ACTIVE && vkey.expires_at ? (
                      <div className="text-xs text-muted-foreground">
                        {expiryHint(vkey.expires_at)}
                      </div>
                    ) : null}
                  </Td>
                  <Td className="text-muted-foreground">
                    {formatDateTime(vkey.last_used_at, '사용 이력 없음')}
                  </Td>
                  <Td numeric>
                    <KeyRowActions vkey={vkey} />
                  </Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      <CursorPagination nextCursor={page.next_cursor} hasMore={page.has_more} className="mt-3" />
    </>
  );
}
