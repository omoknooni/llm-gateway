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
import { getEffectiveModels, getUserAllowedModels } from '@/lib/api/allowed-models';
import { AdminApiError } from '@/lib/api/errors';
import { listModels } from '@/lib/api/models';
import { getTeam } from '@/lib/api/teams';
import { getUser } from '@/lib/api/users';
import { listVirtualKeys } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { formatDateTime } from '@/lib/format/datetime';
import {
  RESOLVED_FROM_LABEL,
  USER_ROLE_LABEL,
  USER_ROLE_TONE,
  VK_STATUS_LABEL,
  VK_STATUS_TONE,
} from '@/lib/format/labels';
import { UserRole, VKOwnerType } from '@/types/api';

export const metadata = { title: '사용자 상세 — llm-gateway Admin' };

export default async function UserDetailPage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  const session = await requirePageAccess('/users');
  const { userId } = await params;
  const isAdmin = session.role === UserRole.ADMIN;

  let user;
  try {
    user = await getUser(userId);
  } catch (error) {
    if (error instanceof AdminApiError && error.isNotFound) notFound();
    throw error;
  }

  const [models, allowed, effective, keys, team] = await Promise.all([
    listModels(),
    getUserAllowedModels(userId),
    getEffectiveModels(userId),
    listVirtualKeys({ owner_type: VKOwnerType.USER, owner_id: userId, limit: 50 }),
    user.team_id ? getTeam(user.team_id).catch(() => null) : Promise.resolve(null),
  ]);

  return (
    <>
      <PageHeader
        title={user.display_name}
        description={user.email}
        actions={
          <Button variant="ghost" size="sm" asChild>
            <Link href="/users">목록으로</Link>
          </Button>
        }
      />

      <div className="space-y-4">
        <Card>
          <CardHeader title="기본 정보" />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="사용자 ID">
                <MonoId value={user.id} truncate={false} />
              </DescriptionItem>
              <DescriptionItem term="역할">
                <Badge tone={USER_ROLE_TONE[user.role]}>{USER_ROLE_LABEL[user.role]}</Badge>
              </DescriptionItem>
              <DescriptionItem term="팀">
                {team ? (
                  <Link href={`/teams/${team.id}`} className="hover:underline">
                    {team.name}
                  </Link>
                ) : (
                  <span className="text-muted-foreground">팀 없음</span>
                )}
              </DescriptionItem>
              <DescriptionItem term="상태">
                <Badge tone={user.is_active ? 'success' : 'neutral'}>
                  {user.is_active ? '활성' : '비활성'}
                </Badge>
              </DescriptionItem>
              <DescriptionItem term="인증 provider">
                <code className="font-mono text-xs">{user.provider}</code>
              </DescriptionItem>
              <DescriptionItem term="마지막 로그인">
                {formatDateTime(user.last_login_at, '기록 없음')}
              </DescriptionItem>
            </DescriptionList>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="실효 허용 모델"
            description="카탈로그 → 팀 → 개인 세 층을 해석한 최종 결과입니다."
            actions={
              <Badge tone={effective.resolved_from === 'USER' ? 'info' : 'neutral'}>
                {RESOLVED_FROM_LABEL[effective.resolved_from]}에서 결정
              </Badge>
            }
          />
          <CardBody>
            {effective.model_aliases.length === 0 ? (
              <p className="text-sm text-danger">
                허용된 모델이 없습니다. 이 사용자는 어떤 모델도 호출할 수 없습니다.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {effective.model_aliases.map((alias) => (
                  <Link key={alias} href={`/models/${alias}`}>
                    <Badge tone="neutral" className="font-mono hover:bg-surface">
                      {alias}
                    </Badge>
                  </Link>
                ))}
              </div>
            )}
            {effective.narrowed_by_key ? (
              <p className="mt-3 text-xs text-muted-foreground">
                일부 Virtual Key 가 이 목록보다 좁은 범위로 제한되어 있습니다.
              </p>
            ) : null}
          </CardBody>
        </Card>

        <AllowedModelsEditor
          scope="user"
          scopeId={user.id}
          title="개인 허용 모델"
          description="설정하면 팀 설정을 덮어씁니다. 해제하면 팀 또는 카탈로그가 다시 이깁니다."
          models={models}
          initialSelection={allowed.model_aliases}
          readOnly={!isAdmin}
        />

        <Card>
          <CardHeader
            title={`소유 Virtual Key (${keys.items.length}${keys.has_more ? '+' : ''})`}
            actions={
              <Button variant="ghost" size="sm" asChild>
                <Link href={`/keys?owner_type=USER&owner_id=${user.id}`}>키 화면에서 보기</Link>
              </Button>
            }
          />
          <Table>
            <THead>
              <Tr>
                <Th>이름</Th>
                <Th>prefix</Th>
                <Th>상태</Th>
                <Th>만료</Th>
                <Th>마지막 사용</Th>
              </Tr>
            </THead>
            <TBody>
              {keys.items.length === 0 ? (
                <TEmpty colSpan={5}>이 사용자가 소유한 Virtual Key 가 없습니다.</TEmpty>
              ) : (
                keys.items.map((key) => (
                  <Tr key={key.id}>
                    <Td className="font-medium">
                      <Link href={`/keys/${key.id}`} className="hover:underline">
                        {key.name}
                      </Link>
                    </Td>
                    <Td>
                      <code className="font-mono text-xs">{key.key_prefix}</code>
                    </Td>
                    <Td>
                      <Badge tone={VK_STATUS_TONE[key.status]}>
                        {VK_STATUS_LABEL[key.status]}
                      </Badge>
                    </Td>
                    <Td className="text-muted-foreground">{formatDateTime(key.expires_at)}</Td>
                    <Td className="text-muted-foreground">
                      {formatDateTime(key.last_used_at, '사용 이력 없음')}
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        </Card>
      </div>
    </>
  );
}
