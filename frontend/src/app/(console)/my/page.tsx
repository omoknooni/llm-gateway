import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
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
import { KeyRowActions } from '@/components/keys/key-row-actions';
import { getEffectiveModels } from '@/lib/api/allowed-models';
import { listVirtualKeys } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { expiryHint, formatDateTime } from '@/lib/format/datetime';
import {
  RESOLVED_FROM_LABEL,
  USER_ROLE_LABEL,
  USER_ROLE_TONE,
  VK_STATUS_LABEL,
  VK_STATUS_TONE,
} from '@/lib/format/labels';
import { VKOwnerType, VKStatus } from '@/types/api';

export const metadata = { title: '내 정보 — llm-gateway Admin' };

/**
 * 내 정보.
 *
 * MEMBER 가 볼 수 있는 유일한 화면입니다. 자기 키를 폐기할 수는 있지만 발급할 수는
 * 없습니다(backend 인가 표). 그래서 발급 버튼이 없습니다.
 */
export default async function MyPage() {
  const session = await requirePageAccess('/my');

  const [effective, keys] = await Promise.all([
    getEffectiveModels(session.userId),
    listVirtualKeys({ owner_type: VKOwnerType.USER, owner_id: session.userId, limit: 100 }),
  ]);

  return (
    <>
      <PageHeader title="내 정보" description="내 계정과 내가 소유한 Virtual Key 입니다." />

      <div className="space-y-4">
        <Card>
          <CardHeader title="계정" />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="이메일">{session.email}</DescriptionItem>
              <DescriptionItem term="역할">
                <Badge tone={USER_ROLE_TONE[session.role]}>
                  {USER_ROLE_LABEL[session.role]}
                </Badge>
              </DescriptionItem>
              <DescriptionItem term="사용자 ID">
                <MonoId value={session.userId} truncate={false} />
              </DescriptionItem>
              <DescriptionItem term="팀">
                {session.teamId ? (
                  <MonoId value={session.teamId} />
                ) : (
                  <span className="text-muted-foreground">팀 없음</span>
                )}
              </DescriptionItem>
            </DescriptionList>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="내가 호출할 수 있는 모델"
            actions={
              <Badge tone="neutral">
                {RESOLVED_FROM_LABEL[effective.resolved_from]}에서 결정
              </Badge>
            }
          />
          <CardBody>
            {effective.model_aliases.length === 0 ? (
              <p className="text-sm text-danger">
                허용된 모델이 없습니다. 팀 관리자에게 문의하세요.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {effective.model_aliases.map((alias) => (
                  <Badge key={alias} tone="neutral" className="font-mono">
                    {alias}
                  </Badge>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="내 Virtual Key"
            description="키 발급은 팀장 또는 플랫폼 관리자에게 요청하세요."
          />
          <Table>
            <THead>
              <Tr>
                <Th>이름</Th>
                <Th>prefix</Th>
                <Th>상태</Th>
                <Th>만료</Th>
                <Th>마지막 사용</Th>
                <Th numeric>동작</Th>
              </Tr>
            </THead>
            <TBody>
              {keys.items.length === 0 ? (
                <TEmpty colSpan={6}>소유한 Virtual Key 가 없습니다.</TEmpty>
              ) : (
                keys.items.map((vkey) => (
                  <Tr key={vkey.id}>
                    <Td className="font-medium">{vkey.name}</Td>
                    <Td>
                      <code className="font-mono text-xs">{vkey.key_prefix}</code>
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
                      {/* 폐기만 노출합니다. 발급·로테이션은 MEMBER 권한 밖입니다. */}
                      <KeyRowActions vkey={vkey} canManage={false} compact />
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        </Card>

        <p className="text-xs text-muted-foreground">
          키를 잃어버렸다면 즉시 폐기하고 재발급을 요청하세요.{' '}
          <Link href="/keys" className="underline-offset-4 hover:underline">
            키 관리 화면
          </Link>
          은 권한이 있는 경우에만 열립니다.
        </p>
      </div>
    </>
  );
}
