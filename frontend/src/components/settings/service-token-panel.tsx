'use client';

import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardHeader } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { Field, Input } from '@/components/ui/field';
import { SecretRevealDialog } from '@/components/ui/secret-dialog';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import {
  issueServiceTokenAction,
  revokeServiceTokenAction,
  rotateServiceTokenAction,
} from '@/lib/actions/service-tokens';
import { expiryHint, formatDateTime } from '@/lib/format/datetime';
import { useAction } from '@/lib/use-action';
import type { ServiceTokenResponse } from '@/types/api';

/**
 * 서비스 토큰 관리.
 *
 * 외부 시스템·배치가 Admin API 를 호출할 때 쓰는 자격 증명입니다. 검증되면 ADMIN 권한을
 * 갖고 감사 로그에 `is_service_token=true` 로 드러납니다.
 */
export function ServiceTokenPanel({ tokens }: { tokens: ServiceTokenResponse[] }) {
  const [issueOpen, setIssueOpen] = useState(false);
  const [rotateTarget, setRotateTarget] = useState<ServiceTokenResponse | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ServiceTokenResponse | null>(null);
  const [revealed, setRevealed] = useState<{ token: string; prefix: string } | null>(null);

  const [name, setName] = useState('');
  const [days, setDays] = useState('90');

  const issue = useAction(issueServiceTokenAction, {
    onSuccess: (data) => {
      setIssueOpen(false);
      setName('');
      setDays('90');
      setRevealed({ token: data.token, prefix: data.token_prefix });
    },
  });

  const rotate = useAction(rotateServiceTokenAction, {
    onSuccess: (data) => {
      setRotateTarget(null);
      setRevealed({ token: data.token, prefix: data.token_prefix });
    },
  });

  const revoke = useAction(revokeServiceTokenAction, {
    successMessage: '토큰을 폐기했습니다',
    onSuccess: () => setRevokeTarget(null),
  });

  return (
    <Card>
      <CardHeader
        title="서비스 토큰"
        description="배치·외부 시스템이 Admin API 를 호출할 때 쓰는 자격 증명입니다."
        actions={
          <Button variant="primary" size="sm" onClick={() => setIssueOpen(true)}>
            <Plus />토큰 발급
          </Button>
        }
      />
      <Table>
        <THead>
          <Tr>
            <Th>이름</Th>
            <Th>prefix</Th>
            <Th>만료</Th>
            <Th>상태</Th>
            <Th numeric>동작</Th>
          </Tr>
        </THead>
        <TBody>
          {tokens.length === 0 ? (
            <TEmpty colSpan={5}>발급된 서비스 토큰이 없습니다.</TEmpty>
          ) : (
            tokens.map((token) => {
              const revoked = token.revoked_at !== null;
              return (
                <Tr key={token.id}>
                  <Td className="font-medium">{token.name}</Td>
                  <Td>
                    <code className="font-mono text-xs">{token.token_prefix}</code>
                  </Td>
                  <Td>
                    <div className="text-muted-foreground">{formatDateTime(token.expires_at)}</div>
                    {!revoked ? (
                      <div className="text-xs text-muted-foreground">
                        {expiryHint(token.expires_at)}
                      </div>
                    ) : null}
                  </Td>
                  <Td>
                    {revoked ? (
                      <Badge tone="danger">폐기됨</Badge>
                    ) : (
                      <Badge tone="success">활성</Badge>
                    )}
                    {token.rotated_from_id ? (
                      <Badge tone="neutral" className="ml-1">
                        로테이션됨
                      </Badge>
                    ) : null}
                  </Td>
                  <Td numeric>
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={revoked}
                        onClick={() => {
                          setRotateTarget(token);
                          setName(token.name);
                          setDays('90');
                        }}
                      >
                        로테이션
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-danger"
                        disabled={revoked}
                        onClick={() => setRevokeTarget(token)}
                      >
                        폐기
                      </Button>
                    </div>
                  </Td>
                </Tr>
              );
            })
          )}
        </TBody>
      </Table>

      {/* 발급 */}
      <Dialog open={issueOpen} onOpenChange={setIssueOpen}>
        <DialogContent
          title="서비스 토큰 발급"
          description="원문은 발급 직후 한 번만 표시됩니다."
          footer={
            <>
              <Button variant="ghost" onClick={() => setIssueOpen(false)} disabled={issue.pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={issue.pending}
                onClick={() => void issue.run({ name, expiresInDays: Number(days) })}
              >
                발급
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field
              label="이름"
              htmlFor="svc-name"
              required
              error={issue.fieldErrors['name']}
              hint="어느 시스템이 쓰는 토큰인지 알 수 있게 적으세요"
            >
              <Input
                id="svc-name"
                value={name}
                autoFocus
                placeholder="cost-report-batch"
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field
              label="유효 기간 (일)"
              htmlFor="svc-days"
              required
              error={issue.fieldErrors['expires_in_days']}
            >
              <Input
                id="svc-days"
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(event) => setDays(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      {/* 로테이션 */}
      <Dialog open={rotateTarget !== null} onOpenChange={(open) => !open && setRotateTarget(null)}>
        <DialogContent
          title="서비스 토큰 로테이션"
          description={rotateTarget?.name}
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => setRotateTarget(null)}
                disabled={rotate.pending}
              >
                취소
              </Button>
              <Button
                variant="primary"
                loading={rotate.pending}
                onClick={() =>
                  rotateTarget &&
                  void rotate.run(rotateTarget.id, { name, expiresInDays: Number(days) })
                }
              >
                로테이션
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="이름" htmlFor="svc-rotate-name" required>
              <Input
                id="svc-rotate-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="유효 기간 (일)" htmlFor="svc-rotate-days" required>
              <Input
                id="svc-rotate-days"
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(event) => setDays(event.target.value)}
              />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={revokeTarget !== null}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        title="서비스 토큰 폐기"
        description={`${revokeTarget?.name ?? ''} 을 즉시 폐기합니다. 이 토큰을 쓰는 시스템의 호출이 곧바로 401 이 됩니다.`}
        confirmLabel="폐기"
        pending={revoke.pending}
        onConfirm={() => revokeTarget && void revoke.run(revokeTarget.id)}
      />

      <SecretRevealDialog
        open={revealed !== null}
        onClose={() => setRevealed(null)}
        title="서비스 토큰 원문"
        description={revealed ? `prefix: ${revealed.prefix}` : undefined}
        secret={revealed?.token ?? ''}
      >
        <p className="mt-3 text-xs text-muted-foreground">
          이 토큰은 ADMIN 권한으로 Admin API 전체를 호출할 수 있습니다. 시크릿 저장소에 넣고
          코드나 이미지에 넣지 마세요.
        </p>
      </SecretRevealDialog>
    </Card>
  );
}
