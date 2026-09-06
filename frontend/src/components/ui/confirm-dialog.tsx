'use client';

import { useState, type ReactNode } from 'react';

import { Button } from './button';
import { Dialog, DialogContent } from './dialog';
import { Field, Input } from './field';

/**
 * 파괴적 조작 확인.
 *
 * `confirmPhrase` 를 주면 그 문구를 정확히 입력해야 실행됩니다. 팀 VK 일괄 폐기처럼
 * 되돌릴 수 없는 조작을 예/아니오로 끝내지 않기 위한 장치입니다(01 문서).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = '실행',
  confirmPhrase,
  destructive = true,
  pending = false,
  children,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  confirmPhrase?: string;
  destructive?: boolean;
  pending?: boolean;
  children?: ReactNode;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState('');
  const phraseSatisfied = !confirmPhrase || typed === confirmPhrase;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped('');
        onOpenChange(next);
      }}
    >
      <DialogContent
        title={title}
        description={description}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>
              취소
            </Button>
            <Button
              variant={destructive ? 'danger' : 'primary'}
              onClick={onConfirm}
              disabled={!phraseSatisfied}
              loading={pending}
            >
              {confirmLabel}
            </Button>
          </>
        }
      >
        {children}
        {confirmPhrase ? (
          <Field
            label={
              <>
                확인을 위해 <code className="font-mono">{confirmPhrase}</code> 를 입력하세요
              </>
            }
            htmlFor="confirm-phrase"
            className="mt-4"
          >
            <Input
              id="confirm-phrase"
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
            />
          </Field>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
