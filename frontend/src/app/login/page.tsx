import { KeyRound } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Field, Input, Select } from '@/components/ui/field';
import { UserRole } from '@/types/api';
import { USER_ROLE_LABEL } from '@/lib/format/labels';

export const metadata = { title: '로그인 — llm-gateway Admin' };

/**
 * 로그인.
 *
 * 운영 경로는 사내 SSO(OIDC)이고 IdP 는 아직 확정되지 않았습니다(backend 07 미결정 #1).
 * 그래서 지금 열려 있는 것은 dev 로그인뿐이며, `DEV_LOGIN_ENABLED` 가 꺼진 배포에서
 * 로그인 수단이 없는 것이 **정상 상태**입니다. 화면은 그 사실을 숨기지 않고 알립니다.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  const devEnabled = process.env.DEV_LOGIN_ENABLED === 'true';

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex size-9 items-center justify-center rounded-(--radius-base) bg-primary text-primary-foreground">
            <KeyRound className="size-4" />
          </span>
          <div>
            <p className="text-sm font-semibold">llm-gateway Admin</p>
            <p className="text-xs text-muted-foreground">control plane 관리 콘솔</p>
          </div>
        </div>

        {devEnabled ? (
          <form
            method="POST"
            action="/api/auth/dev-login"
            className="space-y-3 rounded-(--radius-card) border border-border bg-surface p-4"
          >
            <div className="rounded-(--radius-base) border border-warning/30 bg-warning-soft px-3 py-2 text-xs text-warning">
              개발 전용 로그인입니다. 서명을 검증하지 않으며 운영 환경에서는 열리지 않습니다.
            </div>

            <input type="hidden" name="next" value={next ?? '/'} />

            <Field label="이메일" htmlFor="email" hint="감사 로그에 그대로 남습니다">
              <Input id="email" name="email" type="email" defaultValue="admin@dev.local" />
            </Field>

            <Field label="역할" htmlFor="role">
              <Select id="role" name="role" defaultValue={UserRole.ADMIN}>
                {Object.values(UserRole).map((role) => (
                  <option key={role} value={role}>
                    {USER_ROLE_LABEL[role]} ({role})
                  </option>
                ))}
              </Select>
            </Field>

            <Field
              label="팀 ID"
              htmlFor="team_id"
              hint="TEAM_LEADER·MEMBER 로 들어갈 때만 필요합니다. auth.teams 의 UUID."
            >
              <Input id="team_id" name="team_id" placeholder="선택 사항" autoComplete="off" />
            </Field>

            <Button type="submit" variant="primary" className="w-full">
              콘솔 들어가기
            </Button>
          </form>
        ) : (
          <div className="rounded-(--radius-card) border border-border bg-surface p-4 text-sm">
            <p className="font-medium">사용 가능한 로그인 수단이 없습니다</p>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              운영 로그인은 사내 SSO(OIDC)로 들어옵니다. IdP 가 확정되면 이 화면에 SSO 버튼이
              추가됩니다. 로컬 개발이라면 <code className="font-mono">DEV_LOGIN_ENABLED=true</code>
              를 프론트와 backend 양쪽에 설정하세요.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
