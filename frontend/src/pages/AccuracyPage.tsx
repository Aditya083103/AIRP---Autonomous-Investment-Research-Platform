// frontend/src/pages/AccuracyPage.tsx
// AIRP -- Public Accuracy Dashboard page (T-092)
//
// The /accuracy route: a public page (no ProtectedRoute wrapper, see
// AppRoutes.tsx) showing how accurate the Portfolio Manager's past
// BUY/HOLD/SELL verdicts have actually been, built entirely from the
// two public T-091 endpoints -- GET /api/v1/accuracy/summary and
// GET /api/v1/accuracy/history -- neither of which needs a signed-in
// user (see backend/routers/accuracy.py's module docstring for the full
// "why public" rationale this page's own route registration relies on).
//
// Two independent useQuery calls (useAccuracySummary, useAccuracyHistory)
// rather than one combined fetch -- the same reasoning
// AnalysisResultPage.tsx's docstring already gives for keeping
// useAnalysisResult and useAnalysisCharts separate: the two backend
// endpoints have different payload shapes and different failure
// characteristics, so a slow/failed history fetch should never block
// the summary stats from rendering, and vice versa. AccuracyPanel is
// only rendered once BOTH have resolved successfully -- the trend line
// and scatter chart need history entries, and the stat row and bar
// chart need the summary, so a panel built from just one of the two
// would either be half-empty or throw on a missing prop. Splitting the
// "loading" state further (e.g. rendering the bar chart the moment
// summary resolves, independently of history) was considered and
// rejected: it would mean AccuracyPanel's props become partially
// optional, pushing null-handling into every one of its child charts
// for a page whose two queries, in practice, resolve within
// milliseconds of each other against the same backend.

import { AccuracyPanel } from "@/components/charts";
import { AccuracyPanelSkeleton } from "@/components/skeletons";
import { useAccuracyHistory } from "@/hooks/useAccuracyHistory";
import { useAccuracySummary } from "@/hooks/useAccuracySummary";

export function AccuracyPage(): JSX.Element {
  const {
    data: summary,
    isLoading: isSummaryLoading,
    isError: isSummaryError,
    error: summaryError,
  } = useAccuracySummary();

  const {
    data: history,
    isLoading: isHistoryLoading,
    isError: isHistoryError,
    error: historyError,
  } = useAccuracyHistory();

  const isLoading = isSummaryLoading || isHistoryLoading;
  const isError = isSummaryError || isHistoryError;
  const error = summaryError ?? historyError;

  return (
    <div>
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">
        Public accuracy dashboard
      </p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        How right has the committee actually been?
      </h1>
      <p className="mt-2 max-w-2xl text-sm text-muted">
        Every BUY/HOLD/SELL verdict AIRP has issued is tracked against its real market outcome once
        its evaluation horizon elapses, using a ±5% dead-zone directional scoring rule. No account
        needed -- this page is public.
      </p>

      <div className="mt-8">
        {isLoading ? (
          <AccuracyPanelSkeleton label="Loading accuracy data…" />
        ) : isError ? (
          <p role="alert" className="py-12 text-sm text-verdict-sell">
            {error instanceof Error ? error.message : "Could not load accuracy data."}
          </p>
        ) : summary && history ? (
          <AccuracyPanel summary={summary} historyEntries={history.items} />
        ) : null}
      </div>
    </div>
  );
}
