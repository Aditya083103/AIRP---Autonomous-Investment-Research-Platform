// frontend/src/components/skeletons/ResultsPanelSkeleton.tsx
// AIRP -- Results panel skeleton (T-066)
//
// Stands in for <ResultsPanel> (src/components/results/ResultsPanel.tsx)
// while GET /api/v1/analysis/{job_id}/result is pending, on both
// AnalysisResultPage and MemoPage -- the same component shape both
// pages already fetch (useAnalysisResult), so one skeleton composition
// serves both rather than each page hand-rolling its own. Mirrors
// ResultsPanel's actual layout closely enough to avoid a jarring
// reflow when real content replaces it: a verdict-card-shaped block
// first (matching VerdictPanel's `sm:grid-cols-[220px,1fr]` gauge +
// text split), then several shorter "section" blocks for the prose
// sections (executive summary, thesis, bull/bear, risks, valuation).
//
// `role="status"` + a visually-hidden `label` is the one accessible
// announcement for the whole composition -- every individual bar is a
// decorative <Skeleton> (`aria-hidden`, see that component's
// docstring), so a screen reader hears the label once, not once per
// bar.

import { Card, Skeleton } from "@/components/ui";

export interface ResultsPanelSkeletonProps {
  /** Announced once via a visually-hidden status label, e.g. "Loading the Investment Memo…". */
  label: string;
}

/** Placeholder shaped like ResultsPanel: a verdict card, then several prose-section blocks. */
export function ResultsPanelSkeleton({ label }: ResultsPanelSkeletonProps): JSX.Element {
  return (
    <div className="space-y-6" role="status" data-testid="results-panel-skeleton">
      <span className="sr-only">{label}</span>

      <Card>
        <div className="grid gap-6 sm:grid-cols-[220px,1fr] sm:items-center">
          <Skeleton className="mx-auto h-28 w-full max-w-[220px] rounded-full sm:rounded-2xl" />
          <div className="space-y-3">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      </Card>

      {[0, 1, 2].map((index) => (
        <Card key={index}>
          <Skeleton className="h-4 w-40" />
          <div className="mt-3 space-y-2">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-1/2" />
          </div>
        </Card>
      ))}
    </div>
  );
}
