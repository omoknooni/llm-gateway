'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/field';
import { setTeamLeaderAction } from '@/lib/actions/teams';
import { useAction } from '@/lib/use-action';
import type { UserResponse } from '@/types/api';

/**
 * 팀장 지정. 후보는 **그 팀의 멤버**로만 제한합니다.
 *
 * 다른 팀 사람을 고를 수 있게 열어두면 backend 가 거절하는 조합을 화면이 먼저 제안하게 됩니다.
 */
export function TeamLeaderSelect({
  teamId,
  members,
  currentLeaderId,
}: {
  teamId: string;
  members: UserResponse[];
  currentLeaderId: string | null;
}) {
  const [value, setValue] = useState(currentLeaderId ?? '');
  const { run, pending } = useAction(setTeamLeaderAction, {
    successMessage: '팀장을 변경했습니다',
  });

  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs text-muted-foreground">
        팀장
        <Select
          className="mt-1 w-64"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        >
          <option value="">지정하지 않음</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.display_name} ({member.email})
            </option>
          ))}
        </Select>
      </label>
      <Button
        variant="primary"
        loading={pending}
        disabled={value === (currentLeaderId ?? '')}
        onClick={() => void run(teamId, value || null)}
      >
        적용
      </Button>
    </div>
  );
}
