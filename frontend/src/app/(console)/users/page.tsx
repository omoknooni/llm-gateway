import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, PageHeader } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/field';
import { CursorPagination } from '@/components/ui/pagination';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { CreateUserDialog } from '@/components/users/create-user-dialog';
import { UserRowActions } from '@/components/users/user-row-actions';
import { listTeams } from '@/lib/api/teams';
import { listUsers } from '@/lib/api/users';
import { requirePageAccess } from '@/lib/auth/session';
import { formatDateTime } from '@/lib/format/datetime';
import { USER_ROLE_LABEL, USER_ROLE_TONE } from '@/lib/format/labels';
import { UserRole } from '@/types/api';

export const metadata = { title: '사용자 — llm-gateway Admin' };

interface SearchParams {
  team_id?: string;
  role?: string;
  is_active?: string;
  q?: string;
  cursor?: string;
}

function asRole(raw?: string): UserRole | undefined {
  return raw === UserRole.ADMIN || raw === UserRole.TEAM_LEADER || raw === UserRole.MEMBER
    ? raw
    : undefined;
}

export default async function UsersPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const session = await requirePageAccess('/users');
  const params = await searchParams;
  const isAdmin = session.role === UserRole.ADMIN;

  const [page, teamsPage] = await Promise.all([
    listUsers({
      team_id: params.team_id || undefined,
      role: asRole(params.role),
      is_active: params.is_active ? params.is_active === 'true' : undefined,
      q: params.q || undefined,
      cursor: params.cursor,
      limit: 50,
    }),
    listTeams({ limit: 200 }),
  ]);

  const teamName = new Map(teamsPage.items.map((team) => [team.id, team.name]));

  return (
    <>
      <PageHeader
        title="사용자"
        description="IdP 로그인 주체와 연결되는 계정입니다. 역할과 팀이 정책 판정의 축입니다."
        actions={isAdmin ? <CreateUserDialog teams={teamsPage.items} /> : null}
      />

      <form method="GET" className="mb-3 flex flex-wrap items-end gap-2">
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
          역할
          <Select name="role" defaultValue={params.role ?? ''} className="mt-1 w-40">
            <option value="">전체</option>
            {Object.values(UserRole).map((role) => (
              <option key={role} value={role}>
                {USER_ROLE_LABEL[role]}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          상태
          <Select name="is_active" defaultValue={params.is_active ?? ''} className="mt-1 w-32">
            <option value="">전체</option>
            <option value="true">활성</option>
            <option value="false">비활성</option>
          </Select>
        </label>
        <label className="text-xs text-muted-foreground">
          검색
          <Input
            name="q"
            defaultValue={params.q ?? ''}
            placeholder="이메일 또는 표시명"
            className="mt-1 w-56"
          />
        </label>
        <Button type="submit">적용</Button>
        <Button variant="ghost" asChild>
          <Link href="/users">초기화</Link>
        </Button>
        <Button variant="ghost" asChild className="ml-auto">
          <Link href="/users/tree">조직 트리 보기</Link>
        </Button>
      </form>

      <Card>
        <Table>
          <THead>
            <Tr>
              <Th>표시명</Th>
              <Th>이메일</Th>
              <Th>팀</Th>
              <Th>역할</Th>
              <Th>상태</Th>
              <Th>마지막 로그인</Th>
              {isAdmin ? <Th numeric>동작</Th> : null}
            </Tr>
          </THead>
          <TBody>
            {page.items.length === 0 ? (
              <TEmpty colSpan={isAdmin ? 7 : 6}>조건에 맞는 사용자가 없습니다.</TEmpty>
            ) : (
              page.items.map((user) => (
                <Tr key={user.id}>
                  <Td className="font-medium">
                    <Link href={`/users/${user.id}`} className="hover:underline">
                      {user.display_name}
                    </Link>
                  </Td>
                  <Td className="text-muted-foreground">{user.email}</Td>
                  <Td>
                    {user.team_id ? (
                      <Link href={`/teams/${user.team_id}`} className="hover:underline">
                        {teamName.get(user.team_id) ?? user.team_id.slice(0, 8)}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </Td>
                  <Td>
                    <Badge tone={USER_ROLE_TONE[user.role]}>{USER_ROLE_LABEL[user.role]}</Badge>
                  </Td>
                  <Td>
                    <Badge tone={user.is_active ? 'success' : 'neutral'}>
                      {user.is_active ? '활성' : '비활성'}
                    </Badge>
                  </Td>
                  <Td className="text-muted-foreground">{formatDateTime(user.last_login_at)}</Td>
                  {isAdmin ? (
                    <Td numeric>
                      <UserRowActions user={user} teams={teamsPage.items} />
                    </Td>
                  ) : null}
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
