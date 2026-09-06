import { Card, CardBody } from '@/components/ui/card';
import { ServiceTokenPanel } from '@/components/settings/service-token-panel';
import { listServiceTokens } from '@/lib/api/service-tokens';
import { requirePageAccess } from '@/lib/auth/session';

export const metadata = { title: '서비스 토큰 — llm-gateway Admin' };

export default async function ServiceTokensPage({
  searchParams,
}: {
  searchParams: Promise<{ include_revoked?: string }>;
}) {
  await requirePageAccess('/settings');
  const params = await searchParams;
  const includeRevoked = params.include_revoked === 'true';

  const tokens = await listServiceTokens(includeRevoked);

  return (
    <div className="space-y-4">
      <ServiceTokenPanel tokens={tokens} />
      <Card>
        <CardBody>
          <form method="GET" className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              id="include-revoked"
              name="include_revoked"
              value="true"
              defaultChecked={includeRevoked}
              className="size-4 accent-[var(--primary)]"
            />
            <label htmlFor="include-revoked">폐기된 토큰도 표시</label>
            <button
              type="submit"
              className="rounded-(--radius-base) border border-border px-2.5 py-1 text-xs hover:bg-surface-muted"
            >
              적용
            </button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
