'use client';

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/field';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { setAllocationAction } from '@/lib/actions/budgets';
import { compareDecimals, formatUsd, sumDecimals } from '@/lib/format/decimal';
import { ALERT_LEVEL_LABEL, ALERT_LEVEL_TONE, BUDGET_POLICY_LABEL } from '@/lib/format/labels';
import { useAction } from '@/lib/use-action';
import { BudgetPolicy, type AllocationEntry } from '@/types/api';

/**
 * 팀 예산의 멤버 배분.
 *
 * **전체 교체**입니다 — 빈 칸으로 두면 그 멤버의 배분이 해제됩니다. 부분 갱신으로 두면
 * 합계 검증이 "이번에 보낸 것"만 보게 되어 상한을 넘길 수 있습니다(backend 05 문서).
 *
 * 합계는 화면에서 미리 더해 보여주지만 **판정은 backend** 입니다. 초과하면 409 로 전체가
 * 거절되고, 여기서 막는 것은 왕복 한 번을 줄이는 것뿐입니다.
 */
export interface AllocationMember {
  user_id: string;
  display_name: string;
  email: string;
  is_active: boolean;
}

export function AllocationEditor({
  teamId,
  teamLimit,
  budgetConfigured,
  members,
  allocations,
  readOnly = false,
}: {
  teamId: string;
  teamLimit: string;
  budgetConfigured: boolean;
  members: AllocationMember[];
  allocations: AllocationEntry[];
  readOnly?: boolean;
}) {
  const byUser = new Map(allocations.map((entry) => [entry.user_id, entry]));
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(members.map((member) => [member.user_id, byUser.get(member.user_id)?.limit_usd ?? ''])),
  );
  const [policy, setPolicy] = useState<BudgetPolicy>(BudgetPolicy.HARD_BLOCK);

  const save = useAction(
    (input: { allocations: { user_id: string; limit_usd: string }[]; policy: BudgetPolicy }) =>
      setAllocationAction(teamId, input),
    { successMessage: '배분을 저장했습니다' },
  );

  const filled = Object.entries(values).filter(([, value]) => value.trim() !== '');
  const total = sumDecimals(filled.map(([, value]) => value.trim()));
  const exceeds = total !== null && (compareDecimals(total, teamLimit) ?? -1) > 0;

  if (!budgetConfigured) {
    return (
      <Card>
        <CardHeader title="멤버 배분" />
        <CardBody>
          <p className="text-sm text-muted-foreground">
            팀 예산이 없으면 배분할 기준이 없습니다. 먼저 팀 예산을 설정하세요.
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="멤버 배분"
        description="전체 교체입니다. 빈 칸으로 두면 그 멤버의 배분이 해제됩니다."
        actions={
          readOnly ? null : (
            <Button
              variant="primary"
              size="sm"
              loading={save.pending}
              disabled={exceeds}
              onClick={() =>
                void save.run({
                  allocations: filled.map(([user_id, limit_usd]) => ({
                    user_id,
                    limit_usd: limit_usd.trim(),
                  })),
                  policy,
                })
              }
            >
              배분 저장
            </Button>
          )
        }
      />
      <CardBody className="flex flex-wrap items-center gap-4 border-b border-border text-sm">
        <span className="text-muted-foreground">
          팀 한도 <strong className="num text-foreground">{formatUsd(teamLimit)}</strong>
        </span>
        <span className="text-muted-foreground">
          배분 합계{' '}
          <strong className={`num ${exceeds ? 'text-danger' : 'text-foreground'}`}>
            {total === null ? '—' : formatUsd(total)}
          </strong>
        </span>
        {exceeds ? (
          <Badge tone="danger">합계가 팀 한도를 넘습니다. 저장하면 409 로 거절됩니다</Badge>
        ) : null}
        {readOnly ? null : (
          <label className="ml-auto text-xs text-muted-foreground">
            초과 정책
            <Select
              value={policy}
              onChange={(event) => setPolicy(event.target.value as BudgetPolicy)}
              className="mt-1 w-40"
            >
              {Object.values(BudgetPolicy).map((value) => (
                <option key={value} value={value}>
                  {BUDGET_POLICY_LABEL[value]}
                </option>
              ))}
            </Select>
          </label>
        )}
      </CardBody>
      <Table>
        <THead>
          <Tr>
            <Th>멤버</Th>
            <Th numeric>배분 한도 (USD)</Th>
            <Th numeric>소진</Th>
            <Th numeric>소진율</Th>
            <Th>경보</Th>
          </Tr>
        </THead>
        <TBody>
          {members.length === 0 ? (
            <TEmpty colSpan={5}>팀에 멤버가 없습니다.</TEmpty>
          ) : (
            members.map((member) => {
              const entry = byUser.get(member.user_id);
              return (
                <Tr key={member.user_id}>
                  <Td>
                    <div className="font-medium">{member.display_name}</div>
                    <div className="text-xs text-muted-foreground">{member.email}</div>
                  </Td>
                  <Td numeric>
                    {readOnly || !member.is_active ? (
                      <span>{entry ? formatUsd(entry.limit_usd) : '—'}</span>
                    ) : (
                      <Input
                        value={values[member.user_id] ?? ''}
                        inputMode="decimal"
                        placeholder="미배분"
                        className="ml-auto w-32 text-right"
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            [member.user_id]: event.target.value,
                          }))
                        }
                      />
                    )}
                    {save.fieldErrors[`limit_usd:${member.user_id}`] ? (
                      <p className="mt-1 text-xs text-danger">
                        {save.fieldErrors[`limit_usd:${member.user_id}`]}
                      </p>
                    ) : null}
                    {!member.is_active ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        비활성 사용자에게는 배분할 수 없습니다
                      </p>
                    ) : null}
                  </Td>
                  <Td numeric>{entry ? formatUsd(entry.used_usd) : '—'}</Td>
                  <Td numeric>{entry ? `${entry.usage_pct}%` : '—'}</Td>
                  <Td>
                    {entry ? (
                      <Badge tone={ALERT_LEVEL_TONE[entry.alert_level]}>
                        {ALERT_LEVEL_LABEL[entry.alert_level]}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">미배분</span>
                    )}
                  </Td>
                </Tr>
              );
            })
          )}
        </TBody>
      </Table>
    </Card>
  );
}
