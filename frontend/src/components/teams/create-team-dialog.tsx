'use client';

import { Plus } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { Field, Input, Textarea } from '@/components/ui/field';
import { createTeamAction } from '@/lib/actions/teams';
import { useAction } from '@/lib/use-action';

export function CreateTeamDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const { run, pending, fieldErrors } = useAction(createTeamAction, {
    successMessage: '팀을 만들었습니다',
    onSuccess: () => {
      setOpen(false);
      setName('');
      setDescription('');
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          <Plus />팀 만들기
        </Button>
      </DialogTrigger>
      <DialogContent
        title="팀 만들기"
        description="팀은 Virtual Key 소유와 허용 모델 정책의 기본 단위입니다."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant="primary"
              loading={pending}
              onClick={() => void run({ name, description })}
            >
              만들기
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="팀 이름" htmlFor="team-name" required error={fieldErrors['name']}>
            <Input
              id="team-name"
              value={name}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label="설명" htmlFor="team-description" error={fieldErrors['description']}>
            <Textarea
              id="team-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}
