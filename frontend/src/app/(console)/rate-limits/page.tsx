import Link from 'next/link';

import { LimitFormDialog, LimitValues } from '@/components/rate-limits/limit-form-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader, PageHeader } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/field';
import { EmptyState } from '@/components/ui/empty-state';
import { TBody, TEmpty, THead, Table, Td, Th, Tr } from '@/components/ui/table';
import { AdminApiError } from '@/lib/api/errors';
import { listModels } from '@/lib/api/models';
import {
  getRateLimitTree,
  getRateLimitUsage,
  listRateLimits,
} from '@/lib/api/rate-limits';
import { listTeams } from '@/lib/api/teams';
import { requirePageAccess } from '@/lib/auth/session';
import { LIMIT_FIELD_LABEL, RATE_LIMIT_SCOPE_LABEL } from '@/lib/format/labels';
import {
  LIMIT_FIELDS,
  ModelStatus,
  RateLimitScope,
  UserRole,
  type RateLimitTreeResponse,
} from '@/types/api';

export const metadata = { title: 'Rate limit — llm-gateway Admin' };

/**
 * rate limit 설정과 해석.
 *
 * 두 축을 **따로** 그립니다. 주체 축(VK > 사용자 > 팀)과 전역 축(모델별 GLOBAL)은 둘 다
 * 통과해야 요청이 진행되므로, 한 표에 섞으면 "어느 쪽에서 막혔는가"를 설명할 수 없습니다.
 *
 * 폴백은 **한도 종류별로 독립**입니다. 사용자가 tpm 만 정의했다면 rpm 은 팀에서 옵니다.
 * 그래서 트리의 실효값 칸이 종류별로 다른 층을 가리킬 수 있고, 그것이 정상입니다.
 */
export default async function RateLimitsPage({
  searchParams,
}: {
  searchParams: Promise<{ team_id?: string; model_alias?: string }>;
}) {
  const session = await requirePageAccess('/rate-limits');
  const params = await searchParams;
  const isAdmin = session.role === UserRole.ADMIN;
  const modelAlias = params.model_alias?.trim() || undefined;

  // 팀장은 자기 팀 축만 봅니다. 팀 선택도 열어 두지 않습니다 — 어차피 backend 가 403 입니다.
  const teamId = isAdmin ? params.team_id : (session.teamId ?? undefined);

  const [globalLimits, models, teams, tree, usage] = await Promise.all([
    listRateLimits({ scope: RateLimitScope.GLOBAL, model_alias: modelAlias }),
    listModels(ModelStatus.ACTIVE),
    isAdmin ? listTeams({ limit: 200 }) : Promise.resolve(null),
    teamId
      ? getRateLimitTree(teamId, modelAlias).catch((error: unknown) => {
          // 팀장이 다른 팀을 지정한 경우입니다. 화면 전체를 죽이지 않고 그 카드만 비웁니다.
          if (error instanceof AdminApiError && error.isForbidden) return null;
          throw error;
        })
      : Promise.resolve(null),
    getRateLimitUsage({ model_alias: modelAlias }),
  ]);

  const typedTree: RateLimitTreeResponse | null = tree;

  return (
    <>
      <PageHeader
        title="Rate limit"
        description="한도를 정의하는 곳입니다. 집행과 카운팅은 gateway 가 합니다."
      />

      <form method="GET" className="mb-3 flex flex-wrap items-end gap-2">
        {isAdmin && teams ? (
          <label className="text-xs text-muted-foreground">
            팀
            <Select name="team_id" defaultValue={teamId ?? ''} className="mt-1 w-52">
              <option value="">팀 선택</option>
              {teams.items.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </Select>
          </label>
        ) : null}
        <label className="text-xs text-muted-foreground">
          모델
          <Input
            name="model_alias"
            defaultValue={modelAlias ?? ''}
            placeholder="전체 모델"
            className="mt-1 w-44 font-mono"
          />
        </label>
        <Button type="submit">적용</Button>
      </form>

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="전역 한도"
            description="주체 한도와 별개 축입니다. 모든 팀의 합이 provider 쿼터를 넘는 것을 막습니다."
            actions={
              isAdmin && modelAlias ? (
                <LimitFormDialog
                  scope={RateLimitScope.GLOBAL}
                  scopeId={null}
                  modelAlias={modelAlias}
                  label={`전역 · ${modelAlias}`}
                  triggerLabel={`${modelAlias} 한도 설정`}
                />
              ) : null
            }
          />
          {globalLimits.items.length === 0 ? (
            <CardBody>
              <p className="text-sm text-muted-foreground">
                전역 한도가 없습니다.{' '}
                {isAdmin
                  ? '모델을 지정하면 이 자리에서 설정할 수 있습니다.'
                  : '설정은 플랫폼 관리자만 할 수 있습니다.'}
              </p>
              {isAdmin && !modelAlias && models.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {models.map((model) => (
                    <Link key={model.alias} href={`/rate-limits?model_alias=${model.alias}`}>
                      <Badge tone="neutral" className="font-mono">
                        {model.alias}
                      </Badge>
                    </Link>
                  ))}
                </div>
              ) : null}
            </CardBody>
          ) : (
            <Table>
              <THead>
                <Tr>
                  <Th>모델</Th>
                  <Th>한도</Th>
                  {isAdmin ? <Th numeric>동작</Th> : null}
                </Tr>
              </THead>
              <TBody>
                {globalLimits.items.map((config) => (
                  <Tr key={config.id}>
                    <Td className="font-mono text-xs">{config.model_alias ?? '전체 모델'}</Td>
                    <Td>
                      <LimitValues config={config} />
                    </Td>
                    {isAdmin ? (
                      <Td numeric>
                        <LimitFormDialog
                          scope={RateLimitScope.GLOBAL}
                          scopeId={null}
                          {...(config.model_alias ? { modelAlias: config.model_alias } : {})}
                          label={`전역 · ${config.model_alias ?? '전체 모델'}`}
                          current={config}
                        />
                      </Td>
                    ) : null}
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="팀 → 멤버"
            description={
              modelAlias
                ? `모델 ${modelAlias} 차원의 설정과 실효값입니다.`
                : '모델을 지정하지 않은 설정과 실효값입니다.'
            }
            actions={
              typedTree && isAdmin ? (
                <LimitFormDialog
                  scope={RateLimitScope.TEAM}
                  scopeId={typedTree.team_id}
                  {...(modelAlias ? { modelAlias } : {})}
                  label={`팀 ${typedTree.team_name}`}
                  current={typedTree.team_limits}
                  triggerLabel={typedTree.team_limits ? '팀 한도 수정' : '팀 한도 설정'}
                />
              ) : null
            }
          />
          {!typedTree ? (
            <EmptyState
              title="팀을 선택하세요"
              description="팀 한도와 멤버별 실효 한도를 함께 보여줍니다. 팀 한도 설정은 플랫폼 관리자만 할 수 있습니다."
            />
          ) : (
            <Table>
              <THead>
                <Tr>
                  <Th>대상</Th>
                  <Th>직접 설정</Th>
                  {LIMIT_FIELDS.map((field) => (
                    <Th key={field} numeric>
                      {LIMIT_FIELD_LABEL[field]} 실효값
                    </Th>
                  ))}
                  <Th numeric>동작</Th>
                </Tr>
              </THead>
              <TBody>
                <Tr>
                  <Td className="font-medium">
                    팀 · {typedTree.team_name}
                    <div className="text-xs text-muted-foreground">
                      팀 한도는 플랫폼 관리자만 설정합니다
                    </div>
                  </Td>
                  <Td>
                    <LimitValues config={typedTree.team_limits} />
                  </Td>
                  {LIMIT_FIELDS.map((field) => (
                    <Td key={field} numeric className="text-muted-foreground">
                      {typedTree.team_limits?.[field] ?? '—'}
                    </Td>
                  ))}
                  <Td numeric>—</Td>
                </Tr>
                {typedTree.members.length === 0 ? (
                  <TEmpty colSpan={3 + LIMIT_FIELDS.length}>팀에 멤버가 없습니다.</TEmpty>
                ) : (
                  typedTree.members.map((member) => (
                    <Tr key={member.user_id}>
                      <Td>
                        <Link href={`/users/${member.user_id}`} className="font-medium hover:underline">
                          {member.display_name}
                        </Link>
                      </Td>
                      <Td>
                        <LimitValues config={member.own} />
                      </Td>
                      {LIMIT_FIELDS.map((field) => {
                        const resolved = member.effective_limits[field];
                        return (
                          <Td key={field} numeric>
                            <span className="num">{resolved?.value ?? '—'}</span>
                            {resolved?.resolved_from ? (
                              <div className="text-xs text-muted-foreground">
                                {resolved.resolved_from}
                              </div>
                            ) : null}
                          </Td>
                        );
                      })}
                      <Td numeric>
                        <LimitFormDialog
                          scope={RateLimitScope.USER}
                          scopeId={member.user_id}
                          {...(modelAlias ? { modelAlias } : {})}
                          label={member.display_name}
                          current={member.own}
                        />
                      </Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="실시간 사용률"
            description="gateway 의 집행 카운터를 읽습니다. best-effort 이고, 읽지 못하는 것은 정상 상태입니다."
            actions={
              <Badge tone={usage.available ? 'success' : 'neutral'}>
                {usage.available ? '관측 가능' : '관측 불가'}
              </Badge>
            }
          />
          {!usage.available ? (
            <CardBody>
              <p className="text-sm text-muted-foreground">
                {usage.reason ?? '집행 카운터 키 규약이 확정되기 전이라 값을 읽을 수 없습니다.'}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                설정과 해석은 이 상태와 무관하게 동작합니다.
              </p>
            </CardBody>
          ) : (
            <Table>
              <THead>
                <Tr>
                  <Th>scope</Th>
                  <Th>모델</Th>
                  <Th numeric>한도</Th>
                  <Th numeric>현재</Th>
                  <Th numeric>사용률</Th>
                </Tr>
              </THead>
              <TBody>
                {usage.entries.length === 0 ? (
                  <TEmpty colSpan={5}>표시할 카운터가 없습니다.</TEmpty>
                ) : (
                  usage.entries.map((entry) => (
                    <Tr key={`${entry.scope}:${entry.scope_id}:${entry.model_alias}`}>
                      <Td>
                        {RATE_LIMIT_SCOPE_LABEL[entry.scope]}
                        {entry.scope_id ? (
                          <div className="font-mono text-xs text-muted-foreground">
                            {entry.scope_id}
                          </div>
                        ) : null}
                      </Td>
                      <Td className="font-mono text-xs">{entry.model_alias ?? '전체'}</Td>
                      <Td numeric>{entry.limit_value ?? '—'}</Td>
                      <Td numeric>{entry.current_value ?? '—'}</Td>
                      <Td numeric>{entry.usage_pct === null ? '—' : `${entry.usage_pct}%`}</Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
