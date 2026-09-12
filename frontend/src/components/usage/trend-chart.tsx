import { cn } from '@/lib/cn';
import { formatCount, type FilledBucket } from '@/lib/format/usage';
import { formatUsd } from '@/lib/format/decimal';
import { UsageMetric } from '@/types/api';

/**
 * 추이 막대.
 *
 * **차트 라이브러리를 쓰지 않습니다**(02 문서 미결정 #2 결론). 필요한 것은 "어느 날 튀었는가"
 * 하나이고, 그건 CSS 막대로 충분합니다. 라이브러리는 번들과 테마·SSR 대응 비용을 함께
 * 들여옵니다. 축·범례·줌이 필요해지는 지표가 생기면 그때 도입합니다.
 *
 * 막대 높이 계산에는 금액을 수로 바꿉니다. **표시값은 문자열 그대로**이고, 수는 픽셀 비율을
 * 정하는 데에만 씁니다 — 정밀도 규약(AGENTS.md)이 깨지는 지점은 화면에 찍히는 값입니다.
 */
function valueOf(bucket: FilledBucket, metric: UsageMetric): number {
  if (!bucket.totals) return 0;
  if (metric === UsageMetric.COST) return Number(bucket.totals.estimated_cost_usd);
  if (metric === UsageMetric.TOKENS) return bucket.totals.total_tokens;
  return bucket.totals.request_count;
}

function labelOf(bucket: FilledBucket, metric: UsageMetric): string {
  if (!bucket.totals) return '집계 없음';
  if (metric === UsageMetric.COST) return formatUsd(bucket.totals.estimated_cost_usd);
  if (metric === UsageMetric.TOKENS) return `${formatCount(bucket.totals.total_tokens)} 토큰`;
  return `${formatCount(bucket.totals.request_count)} 호출`;
}

export function TrendChart({
  buckets,
  metric,
}: {
  buckets: FilledBucket[];
  metric: UsageMetric;
}) {
  const max = Math.max(...buckets.map((bucket) => valueOf(bucket, metric)), 0);

  if (buckets.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">표시할 기간이 없습니다.</p>;
  }

  return (
    <div>
      <div className="flex h-32 items-end gap-px" role="img" aria-label="기간별 추이">
        {buckets.map((bucket) => {
          const value = valueOf(bucket, metric);
          // 0 인 날도 막대가 보여야 "호출이 없던 날"로 읽힙니다. 집계가 없는 날은 구멍입니다.
          const height = max > 0 ? Math.max((value / max) * 100, value > 0 ? 2 : 0) : 0;
          return (
            <div
              key={bucket.bucket}
              className="flex h-full flex-1 items-end"
              title={`${bucket.bucket} · ${labelOf(bucket, metric)}`}
            >
              {bucket.totals ? (
                <div
                  className={cn(
                    'w-full rounded-t-[2px]',
                    value > 0 ? 'bg-primary' : 'bg-border',
                  )}
                  style={{ height: `${value > 0 ? height : 2}%` }}
                />
              ) : (
                <div className="h-full w-full border-x border-dashed border-border/40" />
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-muted-foreground">
        <span>{buckets[0]?.bucket}</span>
        <span>{buckets[buckets.length - 1]?.bucket}</span>
      </div>
    </div>
  );
}
