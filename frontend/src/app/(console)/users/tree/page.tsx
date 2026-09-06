import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { getOrgTree } from '@/lib/api/users';
import { requirePageAccess } from '@/lib/auth/session';
import { USER_ROLE_LABEL, USER_ROLE_TONE } from '@/lib/format/labels';

export const metadata = { title: '조직 트리 — llm-gateway Admin' };

export default async function OrgTreePage() {
  await requirePageAccess('/users');
  const tree = await getOrgTree();

  return (
    <>
      <PageHeader
        title="조직 트리"
        description="팀과 소속 멤버를 한눈에 봅니다. 팀장은 별도로 표시됩니다."
        actions={
          <Button variant="ghost" size="sm" asChild>
            <Link href="/users">목록으로</Link>
          </Button>
        }
      />

      {tree.length === 0 ? (
        <Card>
          <EmptyState
            title="표시할 팀이 없습니다"
            description="먼저 팀을 만들고 사용자를 배치하세요."
            action={
              <Button variant="primary" size="sm" asChild>
                <Link href="/teams">팀 관리로 이동</Link>
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {tree.map((team) => (
            <Card key={team.id}>
              <CardHeader
                title={
                  <Link href={`/teams/${team.id}`} className="hover:underline">
                    {team.name}
                  </Link>
                }
                description={`멤버 ${team.members.length}명`}
                actions={
                  team.is_active ? null : <Badge tone="neutral">비활성 팀</Badge>
                }
              />
              <CardBody>
                {team.members.length === 0 ? (
                  <p className="py-3 text-sm text-muted-foreground">소속 멤버가 없습니다.</p>
                ) : (
                  <ul className="divide-y divide-[var(--border)]">
                    {team.members.map((member) => (
                      <li key={member.id} className="flex items-center gap-2 py-2">
                        <Link
                          href={`/users/${member.id}`}
                          className="min-w-0 flex-1 truncate text-sm hover:underline"
                        >
                          <span className="font-medium">{member.display_name}</span>
                          <span className="ml-1.5 text-muted-foreground">{member.email}</span>
                        </Link>
                        {member.id === team.leader_user_id ? (
                          <Badge tone="info">팀장</Badge>
                        ) : null}
                        <Badge tone={USER_ROLE_TONE[member.role]}>
                          {USER_ROLE_LABEL[member.role]}
                        </Badge>
                        {member.is_active ? null : <Badge tone="neutral">비활성</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
