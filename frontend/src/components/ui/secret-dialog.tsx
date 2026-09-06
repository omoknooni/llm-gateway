'use client';

import { ShieldAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Button } from './button';
import { CopyButton } from './copy-button';
import { Dialog, DialogContent } from './dialog';
import { Checkbox } from './field';

/**
 * 원문 1회 노출 다이얼로그.
 *
 * Virtual Key 와 서비스 토큰 원문은 발급·로테이션 응답에서만 볼 수 있습니다. 재조회 경로가
 * 없으므로(backend 03 문서) 여기서 놓치면 키를 다시 발급하는 수밖에 없습니다.
 *
 * 그래서 이 다이얼로그는:
 *  - 바깥 클릭과 ESC 로 닫히지 않습니다.
 *  - "복사했다"를 체크해야 닫을 수 있습니다.
 *  - 닫히는 순간 부모가 상태를 비워 값이 메모리에서 사라집니다.
 *
 * 값을 URL·로그·토스트에 싣지 않습니다.
 */
export function SecretRevealDialog({
  open,
  onClose,
  title,
  secret,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  secret: string;
  description?: ReactNode;
  children?: ReactNode;
}) {
  const [acknowledged, setAcknowledged] = useState(false);

  const close = () => {
    setAcknowledged(false);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && acknowledged && close()}>
      <DialogContent
        title={title}
        description={description}
        dismissible={false}
        footer={
          <Button variant="primary" onClick={close} disabled={!acknowledged}>
            닫기
          </Button>
        }
      >
        <div className="flex items-start gap-2 rounded-(--radius-base) border border-warning/30 bg-warning-soft px-3 py-2 text-xs text-warning">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>
            이 값은 지금 한 번만 표시됩니다. 다시 조회할 수 없으며, 놓치면 재발급해야 합니다.
          </p>
        </div>

        <div className="mt-3 rounded-(--radius-base) border border-border bg-surface-muted p-3">
          <code className="block font-mono text-xs break-all select-all">{secret}</code>
          <div className="mt-2 flex justify-end">
            <CopyButton value={secret} label="원문 복사" />
          </div>
        </div>

        {children}

        <label className="mt-4 flex items-center gap-2 text-xs">
          <Checkbox
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          안전한 곳에 저장했습니다
        </label>
      </DialogContent>
    </Dialog>
  );
}
