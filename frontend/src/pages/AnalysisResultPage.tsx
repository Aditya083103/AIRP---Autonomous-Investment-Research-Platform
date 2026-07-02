// frontend/src/pages/AnalysisResultPage.tsx
// AIRP -- Analysis Result page (T-057 placeholder, live viewer added T-059)
//
// T-057 built this route purely as an honest "coming soon" placeholder
// -- the target AnalysisPage.tsx (T-058) redirects to right after
// POST /analysis/start succeeds. T-059 gives it its real first job:
// connect to WS /api/v1/analysis/{job_id}/stream (useAnalysisStream,
// T-049) and render AgentProgressBoard while the pipeline runs.
//
// The full verdict panel, bull/bear case, and Investment Memo are still
// T-061 -- this page shows a "what happens next" note once is_final
// arrives rather than pretending to render the memo itself.

import { useParams } from "react-router-dom";

import { AgentProgressBoard } from "@/components/progress/AgentProgressBoard";
import { useAnalysisStream } from "@/hooks/useAnalysisStream";
import { useAuth } from "@/hooks/useAuth";

export function AnalysisResultPage(): JSX.Element {
  const { jobId } = useParams<{ jobId: string }>();
  const { accessToken } = useAuth();

  const { events, isComplete, progressPercent, connectionStatus, error } = useAnalysisStream({
    jobId: jobId ?? "",
    token: accessToken ?? "",
    enabled: jobId !== undefined && accessToken !== null,
  });

  const lastEvent = events.length > 0 ? events[events.length - 1] : undefined;
  const hasFailed = lastEvent?.status === "failed";

  if (jobId === undefined) {
    return (
      <div className="mx-auto max-w-lg py-16 text-center">
        <p className="text-sm text-muted">No analysis job specified.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl py-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Live analysis</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        The committee is on the case.
      </h1>
      <p className="mt-2 font-mono text-xs text-muted">Job ID: {jobId}</p>

      <div className="mt-8">
        <AgentProgressBoard
          events={events}
          isComplete={isComplete}
          progressPercent={progressPercent}
          connectionStatus={connectionStatus}
          error={error}
        />
      </div>

      {isComplete ? (
        <div className="mt-10 rounded-card border border-line bg-surface p-6">
          {hasFailed ? (
            <>
              <h2 className="text-lg font-semibold text-ink">This analysis did not complete.</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                {lastEvent?.output_preview ||
                  "The pipeline stopped before producing a verdict. You can start a new " +
                    "analysis from the analysis page."}
              </p>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-ink">Analysis complete.</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                The full verdict panel, bull/bear case, and downloadable Investment Memo for this
                analysis land here in T-061. For now, the committee&apos;s final output is shown
                above on the Portfolio Manager&apos;s card.
              </p>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
