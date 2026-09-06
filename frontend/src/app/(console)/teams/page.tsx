import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/card';
import { MonoId } from '@/components/ui/copy-button';
import { Badge } from '@/components/ui/badge';
import { CursorPagination } from '@/components/ui/pagination';
import { Select } from '@/components/ui/field';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { CreateTeamDialog } from '@/components/teams/create-team-dialog';
import { EditTeamDialog } from '@/components/teams/edit-team-dialog';
import { listTeams } from '@/lib/api/teams';
import { requirePageAccess } from '@/lib/auth/session';
import { formatDate } from '@/lib/format/datetime';
import { UserRole } from '@/types/api';

export const metadata = { title: '팀 — llm-gateway Admin' };

interface SearchParams {
  is_active?: string;
  cursor?: string;
}

export default async function TeamsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await requirePageAccess('/teams');
  const params = await searchParams;
  const isAdmin = session.role === UserRole.ADMIN;

  const page = await listTeams({
    is_active: params.is_active === '' || params.is_active === undefined
      ? undefined
      : params.is_active === 'true',
    cursor: params.cursor,
    limit: 50,
  });

  return (
    <>
      <PageHeader
        title="팀"
        description="Virtual Key 소유와 허용 모델 정책의 기본 단위입니다."
        actions={isAdmin ? <CreateTeamDialog /> : null}
      />

      <form method="GET" className="mb-3 flex items-end gap-2">
        <label className="text-xs text-muted-foreground">
          상태
          <Select name="is_active" defaultValue={params.is_active ?? ''} className="mt-1 w-40">
            <option value="">전체</option>
            <option value="true">활성</option>
            <option value="false">비활성</option>
          </Select>
        </label>
        <Button type="submit" size="md">
          적용
        </Button>
      </form>

      <Card>
        <Table>
          <THead>
            <Tr>
              <Th>이름</Th>
              <Th>설명</Th>
              <Th>팀장</Th>
              <Th>상태</Th>
              <Th>생성일</Th>
              <Th numeric>동작</Th>
            </Tr>
          </THead>
          <TBody>
            {page.items.length === 0 ? (
              <TEmpty colSpan={6}>조건에 맞는 팀이 없습니다.</TEmpty>
            ) : (
              page.items.map((team) => (
                <Tr key={team.id}>
                  <Td className="font-medium">
                    <Link href={`/teams/${team.id}`} className="hover:underline">
                      {team.name}
                    </Link>
                  </Td>
                  <Td className="text-muted-foreground">{team.description ?? '—'}</Td>
                  <Td>
                    {team.leader_user_id ? (
                      <Link href={`/users/${team.leader_user_id}`} className="hover:underline">
                        <MonoId value={team.leader_user_id} />
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">미지정</span>
                    )}
                  </Td>
                  <Td>
                    <Badge tone={team.is_active ? 'success' : 'neutral'}>
                      {team.is_active ? '활성' : '비활성'}
                    </Badge>
                  </Td>
                  <Td className="text-muted-foreground">{formatDate(team.created_at)}</Td>
                  <Td numeric>
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/teams/${team.id}`}>상세</Link>
                      </Button>
                      {isAdmin ? (
                        <EditTeamDialog
                          team={team}
                          trigger={
                            <Button variant="ghost" size="sm">
                              수정
                            </Button>
                          }
                        />
                      ) : null}
                    </div>
                  </Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      <CursorPagination
        nextCursor={page.next_cursor}
        hasMore={page.has_more}
        className="mt-3"
      />
    </>
  );
}
