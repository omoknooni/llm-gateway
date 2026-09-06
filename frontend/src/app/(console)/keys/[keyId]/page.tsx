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
import { KeyRowActions } from '@/components/keys/key-row-actions';
import { AdminApiError } from '@/lib/api/errors';
import { getVirtualKey, getVirtualKeyAudit } from '@/lib/api/virtual-keys';
import { requirePageAccess } from '@/lib/auth/session';
import { expiryHint, formatDateTime } from '@/lib/format/datetime';
import {
  VK_OWNER_TYPE_LABEL,
  VK_STATUS_LABEL,
  VK_STATUS_TONE,
  auditActionLabel,
} from '@/lib/format/labels';
import { VKOwnerType, VKStatus } from '@/types/api';

export const metadata = { title: 'Virtual Key 상세 — llm-gateway Admin' };

export default async function KeyDetailPage({
  params,
}: {
  params: Promise<{ keyId: string }>;
}) {
  await requirePageAccess('/keys');
  const { keyId } = await params;

  let vkey;
  try {
    vkey = await getVirtualKey(keyId);
  } catch (error) {
    if (error instanceof AdminApiError && error.isNotFound) notFound();
    throw error;
  }

  // 감사 조회는 ADMIN·TEAM_LEADER 만 통과합니다. 권한이 없으면 화면 나머지는 그대로 보여줍니다.
  const audit = await getVirtualKeyAudit(keyId).catch((error) => {
    if (error instanceof AdminApiError && error.isForbidden) return null;
    throw error;
  });

  const ownerHref =
    vkey.owner_type === VKOwnerType.TEAM ? `/teams/${vkey.owner_id}` : `/users/${vkey.owner_id}`;

  return (
    <>
      <PageHeader
        title={vkey.name}
        description={
          <span className="font-mono text-xs">{vkey.key_prefix}</span>
        }
        actions={
          <>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/keys">목록으로</Link>
            </Button>
            <KeyRowActions vkey={vkey} />
          </>
        }
      />

      <div className="space-y-4">
        <Card>
          <CardHeader title="기본 정보" />
          <CardBody>
            <DescriptionList>
              <DescriptionItem term="키 ID">
                <MonoId value={vkey.id} truncate={false} />
              </DescriptionItem>
              <DescriptionItem term="상태">
                <Badge tone={VK_STATUS_TONE[vkey.status]}>{VK_STATUS_LABEL[vkey.status]}</Badge>
                {vkey.status === VKStatus.ROTATED ? (
                  <span className="ml-2 text-xs text-warning">
                    유예 기간 동안에는 이 키도 아직 통합니다
                  </span>
                ) : null}
              </DescriptionItem>
              <DescriptionItem term="소유">
                {VK_OWNER_TYPE_LABEL[vkey.owner_type]}{' '}
                <Link href={ownerHref} className="hover:underline">
                  <MonoId value={vkey.owner_id} />
                </Link>
              </DescriptionItem>
              <DescriptionItem term="소속 팀">
                <Link href={`/teams/${vkey.team_id}`} className="hover:underline">
                  <MonoId value={vkey.team_id} />
                </Link>
              </DescriptionItem>
              <DescriptionItem term="만료">
                {formatDateTime(vkey.expires_at)}
                {vkey.expires_at ? (
                  <span className="ml-2 text-xs text-muted-foreground">
                    {expiryHint(vkey.expires_at)}
                  </span>
                ) : null}
              </DescriptionItem>
              <DescriptionItem term="마지막 사용">
                {formatDateTime(vkey.last_used_at, '사용 이력 없음')}
              </DescriptionItem>
              <DescriptionItem term="발급 / 수정">
                {formatDateTime(vkey.created_at)} / {formatDateTime(vkey.updated_at)}
              </DescriptionItem>
              {vkey.revoked_at ? (
                <DescriptionItem term="폐기">
                  {formatDateTime(vkey.revoked_at)}
                  {vkey.revoke_reason ? (
                    <span className="ml-2 text-muted-foreground">({vkey.revoke_reason})</span>
                  ) : null}
                </DescriptionItem>
              ) : null}
            </DescriptionList>

            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground">키 단위 허용 모델 축소</p>
              {vkey.allowed_model_aliases.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">
                  축소하지 않음 — 소유자의 실효 허용 모델을 그대로 씁니다.
                </p>
              ) : (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {vkey.allowed_model_aliases.map((alias) => (
                    <Badge key={alias} tone="neutral" className="font-mono">
                      {alias}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </CardBody>
        </Card>

        {audit ? (
          <>
            <Card>
              <CardHeader
                title="로테이션 체인"
                description="이 키가 어떤 키를 이어받았고, 어떤 키로 이어졌는지."
              />
              <CardBody>
                {audit.rotation_chain.length <= 1 ? (
                  <p className="text-sm text-muted-foreground">로테이션 이력이 없습니다.</p>
                ) : (
                  <ol className="flex flex-wrap items-center gap-2">
                    {audit.rotation_chain.map((id, index) => (
                      <li key={id} className="flex items-center gap-2">
                        {index > 0 ? <span className="text-muted-foreground">→</span> : null}
                        {id === vkey.id ? (
                          <Badge tone="info">
                            <span className="font-mono">{id.slice(0, 8)}</span> (현재)
                          </Badge>
                        ) : (
                          <Link href={`/keys/${id}`}>
                            <Badge tone="neutral" className="font-mono hover:bg-surface">
                              {id.slice(0, 8)}
                            </Badge>
                          </Link>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="감사 이력"
                description="누가 언제 왜 이 키를 손댔는지. 조회는 기록되지 않습니다."
              />
              <CardBody>
                {audit.entries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">기록이 없습니다.</p>
                ) : (
                  <ol className="space-y-3">
                    {audit.entries.map((entry, index) => (
                      <li
                        key={`${entry.occurred_at}-${index}`}
                        className="border-l-2 border-border pl-3"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium">
                            {auditActionLabel(entry.action)}
                          </span>
                          <Badge tone={entry.result === 'SUCCESS' ? 'success' : 'danger'}>
                            {entry.result}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {formatDateTime(entry.occurred_at)}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {entry.actor_role} · <MonoId value={entry.actor_user_id} />
                        </p>
                        {Object.keys(entry.changes ?? {}).length > 0 ? (
                          <pre className="mt-1.5 overflow-x-auto rounded-(--radius-base) bg-surface-muted p-2 font-mono text-[11px]">
                            {JSON.stringify(entry.changes, null, 2)}
                          </pre>
                        ) : null}
                      </li>
                    ))}
                  </ol>
                )}
              </CardBody>
            </Card>
          </>
        ) : (
          <Card>
            <CardBody>
              <p className="text-sm text-muted-foreground">
                감사 이력을 볼 권한이 없습니다.
              </p>
            </CardBody>
          </Card>
        )}
      </div>
    </>
  );
}
