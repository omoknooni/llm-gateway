'use client';

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/field';
import {
  clearUserAllowedModelsAction,
  setTeamAllowedModelsAction,
  setUserAllowedModelsAction,
} from '@/lib/actions/allowed-models';
import { useAction } from '@/lib/use-action';
import { ModelStatus, type ModelResponse } from '@/types/api';

/**
 * 허용 모델 편집기. 팀·사용자 두 scope 가 같은 컴포넌트를 씁니다.
 *
 * scope 를 prop 으로 받고 Server Action 은 여기서 직접 import 합니다. 서버 컴포넌트에서
 * 함수를 내려주는 방식은 인라인 `'use server'` 를 요구해 경계가 흐려집니다.
 *
 * **빈 목록 저장과 설정 해제는 다른 조작입니다.** 빈 목록은 "아무 모델도 허용하지 않음",
 * 해제는 "이 층을 비워 상위 층이 이기게 함"입니다(backend 04 문서 3층 해석).
 * 그래서 저장과 해제 버튼이 따로 있고, 해제는 사용자 scope 에만 존재합니다.
 */
export function AllowedModelsEditor({
  scope,
  scopeId,
  title,
  description,
  models,
  initialSelection,
  readOnly = false,
}: {
  scope: 'team' | 'user';
  scopeId: string;
  title: string;
  description?: string;
  models: ModelResponse[];
  initialSelection: string[];
  readOnly?: boolean;
}) {
  const [selected, setSelected] = useState<string[]>(initialSelection);

  const save = useAction(
    scope === 'team'
      ? (aliases: string[]) => setTeamAllowedModelsAction(scopeId, aliases)
      : (aliases: string[]) => setUserAllowedModelsAction(scopeId, aliases),
    { successMessage: '허용 모델을 저장했습니다' },
  );

  const clear = useAction(() => clearUserAllowedModelsAction(scopeId), {
    successMessage: '개인 설정을 해제했습니다',
    onSuccess: () => setSelected([]),
  });

  const toggle = (alias: string) => {
    setSelected((current) =>
      current.includes(alias) ? current.filter((item) => item !== alias) : [...current, alias],
    );
  };

  const dirty =
    selected.length !== initialSelection.length ||
    selected.some((alias) => !initialSelection.includes(alias));

  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        actions={
          readOnly ? null : (
            <>
              {scope === 'user' ? (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={clear.pending}
                  disabled={initialSelection.length === 0}
                  onClick={() => void clear.run()}
                >
                  설정 해제
                </Button>
              ) : null}
              <Button
                variant="primary"
                size="sm"
                loading={save.pending}
                disabled={!dirty}
                onClick={() => void save.run(selected)}
              >
                저장
              </Button>
            </>
          )
        }
      />
      <CardBody>
        {models.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            카탈로그에 등록된 모델이 없습니다.
          </p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>선택 {selected.length}개</span>
              {selected.length === 0 ? (
                <Badge tone="warning">
                  빈 목록으로 저장하면 이 범위에서 어떤 모델도 호출할 수 없습니다
                </Badge>
              ) : null}
            </div>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {models.map((model) => (
                <li key={model.alias}>
                  <label className="flex items-center gap-2 rounded-(--radius-base) px-2 py-1.5 text-sm hover:bg-surface-muted">
                    <Checkbox
                      checked={selected.includes(model.alias)}
                      disabled={readOnly}
                      onChange={() => toggle(model.alias)}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      <code className="font-mono text-xs">{model.alias}</code>
                      {model.display_name ? (
                        <span className="ml-1.5 text-muted-foreground">{model.display_name}</span>
                      ) : null}
                    </span>
                    {model.status === ModelStatus.INACTIVE ? (
                      <Badge tone="neutral">비활성</Badge>
                    ) : null}
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardBody>
    </Card>
  );
}
