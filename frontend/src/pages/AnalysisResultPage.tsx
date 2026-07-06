// frontend/src/pages/AnalysisResultPage.tsx
// AIRP -- Analysis Result page (T-057 placeholder, live viewer added T-059,
// debate tab added T-060, full results panel added T-061, charts added T-062)
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
//
// T-062 fetches GET /api/v1/analysis/{job_id}/charts (useAnalysisCharts)
// under the identical gate and renders <ChartsPanel> alongside
// <ResultsPanel> -- a second, independent query rather than folding
// chart data into the T-061 result fetch, since the two endpoints
// have very different failure characteristics (GET /result's decision
// is a single already-computed dict with no partial-failure states;
// GET /charts's own five sources can each independently come back
// null/empty, per that endpoint's docstring) and very different
// payload sizes (a year of daily price points vs one JSON memo) --
// keeping them as separate queries means a slow/failed charts fetch
// never blocks the Investment Memo from rendering, and vice versa.

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ChartsPanel } from "@/components/charts";
import { DebateViewer } from "@/components/debate/DebateViewer";
import { AgentProgressBoard } from "@/components/progress/AgentProgressBoard";
import { ResultsPanel } from "@/components/results";
import { ChartsPanelSkeleton, ResultsPanelSkeleton } from "@/components/skeletons";
import { useAnalysisCharts } from "@/hooks/useAnalysisCharts";
import { useAnalysisResult } from "@/hooks/useAnalysisResult";
import { useAnalysisStream } from "@/hooks/useAnalysisStream";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/toast";

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

  // T-066: useAnalysisStream (T-049) already surfaces `error` inline via
  // AgentProgressBoard's own error banner -- this toast is a secondary,
  // ambient notification of the same event for someone who might not be
  // looking at the progress tab (e.g. they've switched to "Debate
  // transcript"). Runs once per distinct error string; useAnalysisStream
  // resets `error` to null at the start of every new connection attempt
  // (see that hook's own effect), so a fresh error after a reconnect
  // re-triggers this rather than being swallowed as "already toasted".
  useEffect(() => {
    if (error !== null) {
      toast.error(error);
    }
  }, [error]);

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

  const {
    data: chartData,
    isPending: isChartsPending,
    isError: isChartsError,
    error: chartsError,
  } = useAnalysisCharts({
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
                <div className="mt-4">
                  <ResultsPanelSkeleton label="Loading the Investment Memo…" />
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
                  <div className="mt-4 text-right">
                    <Link
                      to={`/analysis/${jobId}/memo`}
                      className="text-sm font-medium text-brand-600 hover:text-brand-700 hover:underline"
                    >
                      View full Investment Memo →
                    </Link>
                  </div>
                </div>
              ) : null}

              {isChartsPending && !isResultPending ? (
                <div className="mt-6">
                  <ChartsPanelSkeleton label="Loading charts…" />
                </div>
              ) : null}

              {isChartsError ? (
                <p className="mt-6 text-sm text-verdict-sell">
                  {chartsError instanceof Error
                    ? chartsError.message
                    : "Could not load the charts. Please try refreshing the page."}
                </p>
              ) : null}

              {chartData ? (
                <div className="mt-6">
                  <ChartsPanel data={chartData} />
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
