// frontend/src/components/skeletons/AccuracyPanelSkeleton.tsx
// AIRP -- Accuracy panel skeleton (T-092)
//
// Stands in for <AccuracyPanel> (src/components/charts/AccuracyPanel.tsx)
// on AccuracyPage while GET /api/v1/accuracy/summary and/or
// GET /api/v1/accuracy/history are pending. Mirrors that panel's actual
// layout -- a 3-tile stat row, one full-width chart block, then a
// 2-column row -- collapsing to stacked columns on mobile the same way
// AccuracyPanel's own `sm:grid-cols-3` / `md:grid-cols-2` do, so the
// real panel replaces this without the page's height jumping around
// once data loads. Mirrors ChartsPanelSkeleton's own structure (T-066)
// applied to AccuracyPanel's different shape.

import { Card, Skeleton } from "@/components/ui";

export interface AccuracyPanelSkeletonProps {
  /** Announced once via a visually-hidden status label, e.g. "Loading accuracy data…". */
  label: string;
}

/** Placeholder shaped like AccuracyPanel: stat tiles, one full-width chart, then a 2-column row. */
export function AccuracyPanelSkeleton({ label }: AccuracyPanelSkeletonProps): JSX.Element {
  return (
    <div className="space-y-4" role="status" data-testid="accuracy-panel-skeleton">
      <span className="sr-only">{label}</span>

      <div className="grid gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <Card key={index}>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-8 w-16" />
          </Card>
        ))}
      </div>

      <Card>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-4 h-[260px] w-full" />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1].map((index) => (
          <Card key={index}>
            <Skeleton className="h-4 w-32" />
            <Skeleton className="mt-4 h-[240px] w-full" />
          </Card>
        ))}
      </div>
    </div>
  );
}
