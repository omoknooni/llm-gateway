import { CacheRetryPanel } from '@/components/settings/cache-retry-panel';
import { requirePageAccess } from '@/lib/auth/session';

export const metadata = { title: '캐시 — llm-gateway Admin' };

export default async function CacheSettingsPage() {
  await requirePageAccess('/settings');
  return <CacheRetryPanel />;
}
