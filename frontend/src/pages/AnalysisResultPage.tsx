// frontend/src/pages/AnalysisResultPage.tsx
// AIRP -- Analysis result placeholder (T-057)
//
// HistoryTable's "View" link (the dashboard's "link to detail"
// acceptance criterion) needs somewhere real to go. The actual verdict
// panel, bull/bear case, and memo rendering are T-061 ("Build Analysis
// Results page") -- out of scope here. This stays a small, honest
// placeholder that at least confirms which job_id was clicked, the
// same pattern AnalysisPage (T-055) and DashboardPage (T-056)
// established for forward-referenced routes.

import { useParams } from "react-router-dom";

export function AnalysisResultPage(): JSX.Element {
  const { jobId } = useParams<{ jobId: string }>();

  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Coming soon</p>
      <h1 className="mt-4 font-display text-3xl font-semibold text-ink">
        The results page is being built.
      </h1>
      <p className="mt-4 text-sm leading-relaxed text-muted">
        The full verdict panel, bull/bear case, and Investment Memo for this analysis land here in
        T-061. Job ID:
      </p>
      <p className="mt-2 break-all font-mono text-xs text-muted">{jobId}</p>
    </div>
  );
}
