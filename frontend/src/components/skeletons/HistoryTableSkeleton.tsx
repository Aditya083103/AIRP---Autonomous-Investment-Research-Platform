// frontend/src/components/skeletons/HistoryTableSkeleton.tsx
// AIRP -- History table skeleton (T-066)
//
// Stands in for <HistoryTable> (src/components/dashboard/HistoryTable.tsx)
// on DashboardPage while GET /api/v1/analysis/history is pending.
// Mirrors that table's column shape (company name + ticker, date,
// verdict badge, conviction score) across a fixed number of rows --
// ROW_COUNT is a guess at a typical page's worth of history, not tied
// to any real page size, since the real row count is exactly what
// isn't known yet.

import { Skeleton } from "@/components/ui";

export interface HistoryTableSkeletonProps {
  /** Announced once via a visually-hidden status label, e.g. "Loading your analysis history…". */
  label: string;
}

const ROW_COUNT = 5;

/** Placeholder shaped like HistoryTable: a header bar, then several shimmering rows. */
export function HistoryTableSkeleton({ label }: HistoryTableSkeletonProps): JSX.Element {
  return (
    <div role="status" data-testid="history-table-skeleton">
      <span className="sr-only">{label}</span>

      <div className="border-b border-line pb-3">
        <Skeleton className="h-3 w-24" />
      </div>

      <div className="divide-y divide-line">
        {Array.from({ length: ROW_COUNT }, (_, index) => (
          <div key={index} className="flex items-center gap-4 py-4">
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-20" />
            </div>
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-4 w-12" />
          </div>
        ))}
      </div>
    </div>
  );
}
