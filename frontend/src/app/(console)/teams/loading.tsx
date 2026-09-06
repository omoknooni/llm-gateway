import { TableSkeleton } from '@/components/ui/skeleton';

export default function Loading() {
  return <TableSkeleton rows={8} columns={6} />;
}
