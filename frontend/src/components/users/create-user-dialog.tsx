'use client';

import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Field, Input, Select } from '@/components/ui/field';
import { createUserAction } from '@/lib/actions/users';
import { USER_ROLE_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { UserRole, type TeamResponse } from '@/types/api';

export function CreateUserDialog({ teams }: { teams: TeamResponse[] }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<UserRole>(UserRole.MEMBER);
  const [teamId, setTeamId] = useState('');

  const { run, pending, fieldErrors } = useAction(createUserAction, {
    successMessage: '사용자를 등록했습니다',
    onSuccess: () => {
      setOpen(false);
      setEmail('');
      setDisplayName('');
      setRole(UserRole.MEMBER);
      setTeamId('');
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          <Plus />사용자 등록
        </Button>
      </DialogTrigger>
      <DialogContent
        title="사용자 등록"
        description="IdP 로그인 시 이메일 또는 subject 로 이 행과 연결됩니다."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={pending}
              onClick={() =>
                void run({ email, display_name: displayName, role, team_id: teamId })
              }
            >
              등록
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field
            label="이메일"
            htmlFor="user-email"
            required
            error={fieldErrors['email']}
            hint="허용 도메인이 설정된 배포에서는 도메인 검사를 통과해야 합니다"
          >
            <Input
              id="user-email"
              type="email"
              value={email}
              autoFocus
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field
            label="표시명"
            htmlFor="user-display-name"
            required
            error={fieldErrors['display_name']}
          >
            <Input
              id="user-display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
          </Field>
          <Field label="역할" htmlFor="user-role">
            <Select
              id="user-role"
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
            >
              {Object.values(UserRole).map((value) => (
                <option key={value} value={value}>
                  {USER_ROLE_LABEL[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="팀" htmlFor="user-team" hint="나중에 팀 이동으로 바꿀 수 있습니다">
            <Select
              id="user-team"
              value={teamId}
              onChange={(event) => setTeamId(event.target.value)}
            >
              <option value="">팀 없음</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}
