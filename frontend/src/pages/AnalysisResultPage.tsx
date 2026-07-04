// frontend/src/pages/AnalysisResultPage.tsx
// AIRP -- Analysis Result page (T-057 placeholder, live viewer added T-059,
// debate tab added T-060, full results panel added T-061)
//
// T-057 built this route purely as an honest "coming soon" placeholder
// -- the target AnalysisPage.tsx (T-058) redirects to right after
// POST /analysis/start succeeds. T-059 gives it its real first job:
// connect to WS /api/v1/analysis/{job_id}/stream (useAnalysisStream,
// T-049) and render AgentProgressBoard while the pipeline runs. T-060
// adds a second view of the same event stream -- DebateViewer -- behind
// a lightweight tab switch, so the committee's live progress and its
// full argument-by-argument transcript don't have to compete for the
// same screen space.
//
// T-061 finally lands the "what happens next" note's promise: once the
// stream reports the pipeline finished (is_final) with a non-failed
// status, this page fetches GET /api/v1/analysis/{job_id}/result
// (useAnalysisResult, wrapping T-050's endpoint) and renders
// <ResultsPanel> -- the full verdict, conviction gauge, bull/bear
// case, risks, catalysts, valuation, and every other
// InvestmentDecisionResponse field -- below the tab switch. The fetch
// is intentionally gated on `isComplete && !hasFailed` rather than
// firing eagerly: a job that failed never reaches
// status='completed' on the backend, so GET /result would only ever
// return a 409 for it (see backend/routers/analysis.py's docstring on
// get_analysis_result_endpoint) -- there is no decision to fetch for a
// failed run.

import { useState } from "react";
import { useParams } from "react-router-dom";

import { DebateViewer } from "@/components/debate/DebateViewer";
import { AgentProgressBoard } from "@/components/progress/AgentProgressBoard";
import { ResultsPanel } from "@/components/results";
import { Spinner } from "@/components/ui";
import { useAnalysisResult } from "@/hooks/useAnalysisResult";
import { useAnalysisStream } from "@/hooks/useAnalysisStream";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/cn";

type ResultView = "progress" | "debate";

const VIEW_TABS: { id: ResultView; label: string }[] = [
  { id: "progress", label: "Agent progress" },
  { id: "debate", label: "Debate transcript" },
];

export function AnalysisResultPage(): JSX.Element {
  const { jobId } = useParams<{ jobId: string }>();
  const { accessToken } = useAuth();
  const [activeView, setActiveView] = useState<ResultView>("progress");

  const { events, isComplete, progressPercent, connectionStatus, error } = useAnalysisStream({
    jobId: jobId ?? "",
    token: accessToken ?? "",
    enabled: jobId !== undefined && accessToken !== null,
  });

  const lastEvent = events.length > 0 ? events[events.length - 1] : undefined;
  const hasFailed = lastEvent?.status === "failed";

  const {
    data: decision,
    isPending: isResultPending,
    isError: isResultError,
    error: resultError,
  } = useAnalysisResult({
    jobId: jobId ?? "",
    accessToken,
    enabled: jobId !== undefined && isComplete && !hasFailed,
  });

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

      <div className="mt-8 flex gap-2 border-b border-line" role="tablist" aria-label="Result view">
        {VIEW_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeView === tab.id}
            onClick={() => setActiveView(tab.id)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              activeView === tab.id
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-muted hover:text-ink",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-6" role="tabpanel">
        {activeView === "progress" ? (
          <AgentProgressBoard
            events={events}
            isComplete={isComplete}
            progressPercent={progressPercent}
            connectionStatus={connectionStatus}
            error={error}
          />
        ) : (
          <DebateViewer events={events} />
        )}
      </div>

      {isComplete ? (
        <div className="mt-10">
          {hasFailed ? (
            <div className="rounded-card border border-line bg-surface p-6">
              <h2 className="text-lg font-semibold text-ink">This analysis did not complete.</h2>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                {lastEvent?.output_preview ||
                  "The pipeline stopped before producing a verdict. You can start a new " +
                    "analysis from the analysis page."}
              </p>
            </div>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-ink">Analysis complete.</h2>

              {isResultPending ? (
                <div className="mt-4 flex items-center gap-2 text-sm text-muted">
                  <Spinner size="sm" aria-hidden="true" />
                  Loading the Investment Memo…
                </div>
              ) : null}

              {isResultError ? (
                <p className="mt-4 text-sm text-verdict-sell">
                  {resultError instanceof Error
                    ? resultError.message
                    : "Could not load the Investment Memo. Please try refreshing the page."}
                </p>
              ) : null}

              {decision ? (
                <div className="mt-6">
                  <ResultsPanel decision={decision} />
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
