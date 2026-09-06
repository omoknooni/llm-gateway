'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Checkbox, Field, Input, Textarea } from '@/components/ui/field';
import { updateTeamAction } from '@/lib/actions/teams';
import { useAction } from '@/lib/use-action';
import type { TeamResponse } from '@/types/api';

export function EditTeamDialog({
  team,
  trigger,
}: {
  team: TeamResponse;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? '');
  const [isActive, setIsActive] = useState(team.is_active);

  const { run, pending, fieldErrors } = useAction(updateTeamAction, {
    successMessage: '팀 정보를 수정했습니다',
    onSuccess: () => setOpen(false),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setName(team.name);
          setDescription(team.description ?? '');
          setIsActive(team.is_active);
        }
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        title="팀 수정"
        description={team.name}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={pending}
              onClick={() =>
                void run(team.id, { name, description, is_active: isActive })
              }
            >
              저장
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="팀 이름" htmlFor={`name-${team.id}`} required error={fieldErrors['name']}>
            <Input
              id={`name-${team.id}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label="설명" htmlFor={`desc-${team.id}`}>
            <Textarea
              id={`desc-${team.id}`}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
            />
            활성 팀
          </label>
        </div>
      </DialogContent>
    </Dialog>
  );
}
