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
import { MonoId } from '@/components/ui/copy-button';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { AllowedModelsEditor } from '@/components/models/allowed-models-editor';
import { EditTeamDialog } from '@/components/teams/edit-team-dialog';
import { RevokeAllKeysCard } from '@/components/teams/revoke-all-keys-card';
import { TeamLeaderSelect } from '@/components/teams/team-leader-select';
import { getTeamAllowedModels } from '@/lib/api/allowed-models';
import { AdminApiError } from '@/lib/api/errors';
import { listModels } from '@/lib/api/models';
import { getTeam, listTeamMembers } from '@/lib/api/teams';
import { requirePageAccess } from '@/lib/auth/session';
import { formatDateTime } from '@/lib/format/datetime';
import { USER_ROLE_LABEL, USER_ROLE_TONE } from '@/lib/format/labels';
import { UserRole } from '@/types/api';

export const metadata = { title: '팀 상세 — llm-gateway Admin' };

export default async function TeamDetailPage({
  params,
}: {
  params: Promise<{ teamId: string }>;
}) {
  const session = await requirePageAccess('/teams');
  const { teamId } = await params;
  const isAdmin = session.role === UserRole.ADMIN;

  let team;
  try {
    team = await getTeam(teamId);
  } catch (error) {
    if (error instanceof AdminApiError && error.isNotFound) notFound();
    throw error;
  }

  const [members, models, allowed] = await Promise.all([
    listTeamMembers(teamId),
    listModels(),
    getTeamAllowedModels(teamId),
  ]);

  const leader = members.find((member) => member.id === team.leader_user_id);

  return (
    <>
      <PageHeader
        title={team.name}
        description={team.description ?? '설명이 없습니다.'}
        actions={
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/keys?team_id=${team.id}`}>이 팀의 Virtual Key</Link>
            </Button>
            {isAdmin ? (
              <EditTeamDialog
                team={team}
                trigger={
                  <Button variant="secondary" size="sm">
                    팀 수정
                  </Button>
                }
              />
            ) : null}
          </>
        }
      />

      <div className="space-y-4">
        <Card>
          <CardHeader title="기본 정보" />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="팀 ID">
                <MonoId value={team.id} truncate={false} />
              </DescriptionItem>
              <DescriptionItem term="상태">
                <Badge tone={team.is_active ? 'success' : 'neutral'}>
                  {team.is_active ? '활성' : '비활성'}
                </Badge>
              </DescriptionItem>
              <DescriptionItem term="팀장">
                {leader ? (
                  <Link href={`/users/${leader.id}`} className="hover:underline">
                    {leader.display_name} ({leader.email})
                  </Link>
                ) : team.leader_user_id ? (
                  // 팀장이 이 팀 멤버가 아닌 상태. 정상 데이터가 아니므로 감추지 않습니다.
                  <span className="text-warning">
                    멤버 목록에 없는 사용자 <MonoId value={team.leader_user_id} />
                  </span>
                ) : (
                  <span className="text-muted-foreground">미지정</span>
                )}
              </DescriptionItem>
              <DescriptionItem term="생성 / 수정">
                {formatDateTime(team.created_at)} / {formatDateTime(team.updated_at)}
              </DescriptionItem>
            </DescriptionList>

            {isAdmin ? (
              <div className="mt-4 border-t border-border pt-4">
                <TeamLeaderSelect
                  teamId={team.id}
                  members={members}
                  currentLeaderId={team.leader_user_id}
                />
              </div>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={`멤버 (${members.length}명)`} />
          <Table>
            <THead>
              <Tr>
                <Th>표시명</Th>
                <Th>이메일</Th>
                <Th>역할</Th>
                <Th>상태</Th>
                <Th>마지막 로그인</Th>
              </Tr>
            </THead>
            <TBody>
              {members.length === 0 ? (
                <TEmpty colSpan={5}>이 팀에 속한 사용자가 없습니다.</TEmpty>
              ) : (
                members.map((member) => (
                  <Tr key={member.id}>
                    <Td className="font-medium">
                      <Link href={`/users/${member.id}`} className="hover:underline">
                        {member.display_name}
                      </Link>
                    </Td>
                    <Td className="text-muted-foreground">{member.email}</Td>
                    <Td>
                      <Badge tone={USER_ROLE_TONE[member.role]}>
                        {USER_ROLE_LABEL[member.role]}
                      </Badge>
                    </Td>
                    <Td>
                      <Badge tone={member.is_active ? 'success' : 'neutral'}>
                        {member.is_active ? '활성' : '비활성'}
                      </Badge>
                    </Td>
                    <Td className="text-muted-foreground">{formatDateTime(member.last_login_at)}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        </Card>

        <AllowedModelsEditor
          scope="team"
          scopeId={team.id}
          title="팀 허용 모델"
          description="비어 있으면 카탈로그의 활성 모델 전체가 허용됩니다. 개인 설정이 있으면 그쪽이 이깁니다."
          models={models}
          initialSelection={allowed.model_aliases}
          readOnly={!isAdmin}
        />

        {isAdmin ? <RevokeAllKeysCard teamId={team.id} teamName={team.name} /> : null}
      </div>
    </>
  );
}
