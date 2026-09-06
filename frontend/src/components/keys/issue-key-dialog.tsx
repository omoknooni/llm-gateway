'use client';

import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Checkbox, Field, Input, Select } from '@/components/ui/field';
import { SecretRevealDialog } from '@/components/ui/secret-dialog';
import { issueVirtualKeyAction } from '@/lib/actions/virtual-keys';
import { toDateTimeLocalValue } from '@/lib/format/datetime';
import { useAction } from '@/lib/use-action';
import {
  VKOwnerType,
  type ModelResponse,
  type TeamResponse,
  type UserResponse,
} from '@/types/api';

/** 브라우저 로컬 시각(`YYYY-MM-DDTHH:mm`)을 backend 가 받는 ISO-8601 UTC 로 바꿉니다. */
function toIso(localValue: string): string {
  return localValue ? new Date(localValue).toISOString() : '';
}

function defaultExpiry(days = 90): string {
  return toDateTimeLocalValue(new Date(Date.now() + days * 86_400_000).toISOString());
}

export function IssueKeyDialog({
  teams,
  users,
  models,
}: {
  teams: TeamResponse[];
  users: UserResponse[];
  models: ModelResponse[];
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [ownerType, setOwnerType] = useState<VKOwnerType>(VKOwnerType.USER);
  const [ownerId, setOwnerId] = useState('');
  const [expiresAt, setExpiresAt] = useState(defaultExpiry());
  const [aliases, setAliases] = useState<string[]>([]);

  /** 원문은 상태에만 잠깐 머물고 다이얼로그를 닫으면 사라집니다. */
  const [issued, setIssued] = useState<{ key: string; prefix: string } | null>(null);

  const { run, pending, fieldErrors } = useAction(issueVirtualKeyAction, {
    onSuccess: (data) => {
      setIssued({ key: data.virtual_key, prefix: data.key_prefix });
      setOpen(false);
      setName('');
      setOwnerId('');
      setAliases([]);
      setExpiresAt(defaultExpiry());
    },
  });

  const owners = ownerType === VKOwnerType.TEAM ? teams : users;

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="primary" size="sm">
            <Plus />키 발급
          </Button>
        </DialogTrigger>
        <DialogContent
          title="Virtual Key 발급"
          description="원문은 발급 직후 한 번만 표시됩니다."
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={pending}
                onClick={() =>
                  void run({
                    name,
                    owner_type: ownerType,
                    owner_id: ownerId,
                    expires_at: toIso(expiresAt),
                    allowed_model_aliases: aliases,
                  })
                }
              >
                발급
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <Field label="키 이름" htmlFor="key-name" required error={fieldErrors['name']}>
              <Input
                id="key-name"
                value={name}
                autoFocus
                placeholder="예: search-service-prod"
                onChange={(event) => setName(event.target.value)}
              />
            </Field>

            <Field label="소유 주체" htmlFor="key-owner-type">
              <Select
                id="key-owner-type"
                value={ownerType}
                onChange={(event) => {
                  setOwnerType(event.target.value as VKOwnerType);
                  setOwnerId('');
                }}
              >
                <option value={VKOwnerType.USER}>개인</option>
                <option value={VKOwnerType.TEAM}>팀</option>
              </Select>
            </Field>

            <Field
              label={ownerType === VKOwnerType.TEAM ? '소유 팀' : '소유 사용자'}
              htmlFor="key-owner"
              required
              error={fieldErrors['owner_id']}
            >
              <Select
                id="key-owner"
                value={ownerId}
                onChange={(event) => setOwnerId(event.target.value)}
              >
                <option value="">선택하세요</option>
                {owners.map((owner) => (
                  <option key={owner.id} value={owner.id}>
                    {'display_name' in owner
                      ? `${owner.display_name} (${owner.email})`
                      : owner.name}
                  </option>
                ))}
              </Select>
            </Field>

            <Field
              label="만료 시각"
              htmlFor="key-expires"
              required
              error={fieldErrors['expires_at']}
              hint="만료 없는 키는 만들 수 없습니다. 최대 기간은 backend 설정을 따릅니다."
            >
              <Input
                id="key-expires"
                type="datetime-local"
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
            </Field>

            <Field
              label="허용 모델 축소"
              hint="선택하지 않으면 소유자의 실효 허용 모델을 그대로 씁니다. 넓힐 수는 없고 좁히기만 됩니다."
            >
              <div className="max-h-40 overflow-y-auto rounded-(--radius-base) border border-border p-2">
                {models.length === 0 ? (
                  <p className="p-2 text-xs text-muted-foreground">등록된 모델이 없습니다.</p>
                ) : (
                  models.map((model) => (
                    <label
                      key={model.alias}
                      className="flex items-center gap-2 rounded-(--radius-base) px-1.5 py-1 text-sm hover:bg-surface-muted"
                    >
                      <Checkbox
                        checked={aliases.includes(model.alias)}
                        onChange={() =>
                          setAliases((current) =>
                            current.includes(model.alias)
                              ? current.filter((item) => item !== model.alias)
                              : [...current, model.alias],
                          )
                        }
                      />
                      <code className="font-mono text-xs">{model.alias}</code>
                    </label>
                  ))
                )}
              </div>
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      <SecretRevealDialog
        open={issued !== null}
        onClose={() => setIssued(null)}
        title="Virtual Key 발급 완료"
        description={issued ? `prefix: ${issued.prefix}` : undefined}
        secret={issued?.key ?? ''}
      >
        <p className="mt-3 text-xs text-muted-foreground">
          이 값을 client 의 <code className="font-mono">Authorization: Bearer</code> 헤더에
          넣습니다. 실제 AWS 자격 증명은 이 키 뒤에 숨어 있고 client 에 노출되지 않습니다.
        </p>
      </SecretRevealDialog>
    </>
  );
}
