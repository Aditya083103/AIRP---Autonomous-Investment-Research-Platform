// frontend/src/components/skeletons/ChartsPanelSkeleton.tsx
// AIRP -- Charts panel skeleton (T-066)
//
// Stands in for <ChartsPanel> (src/components/charts/ChartsPanel.tsx)
// while GET /api/v1/analysis/{job_id}/charts is pending on
// AnalysisResultPage. Mirrors that panel's actual layout -- two
// full-width chart blocks (stock price, revenue/profit), then a
// 3-column row (valuation, sentiment, risk) collapsing to one column
// on mobile the same way ChartsPanel's own `md:grid-cols-3` does --
// so the real charts replace this without the page's height jumping
// around once they load.

import { Card, Skeleton } from "@/components/ui";

export interface ChartsPanelSkeletonProps {
  /** Announced once via a visually-hidden status label, e.g. "Loading charts…". */
  label: string;
}

/** Placeholder shaped like ChartsPanel: two full-width chart blocks, then a 3-column row. */
export function ChartsPanelSkeleton({ label }: ChartsPanelSkeletonProps): JSX.Element {
  return (
    <div className="space-y-4" role="status" data-testid="charts-panel-skeleton">
      <span className="sr-only">{label}</span>

      <Card>
        <Skeleton className="h-4 w-32" />
        <Skeleton className="mt-4 h-[260px] w-full" />
      </Card>

      <Card>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-4 h-[260px] w-full" />
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <Card key={index}>
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-4 h-[200px] w-full" />
          </Card>
        ))}
      </div>
    </div>
  );
}
