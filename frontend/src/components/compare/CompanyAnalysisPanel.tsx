// frontend/src/components/compare/CompanyAnalysisPanel.tsx
// AIRP -- Single-company comparison panel (T-064)
//
// One half of the side-by-side compare view. Owns its own
// useAnalysisStream / useAnalysisResult / useAnalysisCharts calls --
// exactly the same three hooks AnalysisResultPage.tsx (T-061/T-062)
// composes for a single job -- so that ComparePage.tsx can mount two
// of these, one per job_id, and get two genuinely independent,
// parallel analyses: neither panel's WebSocket connection, result
// fetch, or chart fetch is gated on the other one finishing first.
//
// Deliberately renders a compact progress summary (a single
// ProgressBar + latest agent line) rather than the full 8-card
// AgentProgressBoard grid T-059 built -- two of those side by side
// would not fit a normal viewport width, and the compare view's job is
// "is this one done yet", not the full agent-by-agent narrative the
// dedicated result page already tells better on its own.
//
// Reports upward via `onSettled`, called at most once per job with the
// final decision/charts pair once BOTH fetches resolve, or with `null`
// if the run failed or either fetch errored -- see that prop's
// docstring for the exact contract ComparePage.tsx relies on.

import { useEffect, useRef } from "react";

import { Card, ProgressBar, Spinner } from "@/components/ui";
import { useAnalysisCharts } from "@/hooks/useAnalysisCharts";
import { useAnalysisResult } from "@/hooks/useAnalysisResult";
import { useAnalysisStream } from "@/hooks/useAnalysisStream";
import { type AnalysisChartDataResponse, type InvestmentDecisionResponse } from "@/types/analysis";

export interface CompanyAnalysisPanelResult {
  decision: InvestmentDecisionResponse;
  charts: AnalysisChartDataResponse;
}

export interface CompanyAnalysisPanelProps {
  /** Display label, e.g. the company name -- shown above the progress bar. */
  title: string;
  jobId: string;
  accessToken: string;
  /**
   * Called exactly once when this panel reaches a final state:
   * `(result)` once both the decision and chart fetches succeed, or
   * `null` if the pipeline failed or either fetch errored. ComparePage
   * uses this to know when it can render the comparison table -- it
   * never reads decision/chart data out of this component directly.
   */
  onSettled: (result: CompanyAnalysisPanelResult | null) => void;
}

/** Runs and displays the live progress for one side of a two-company comparison. */
export function CompanyAnalysisPanel({
  title,
  jobId,
  accessToken,
  onSettled,
}: CompanyAnalysisPanelProps): JSX.Element {
  const { events, isComplete, progressPercent, connectionStatus, error } = useAnalysisStream({
    jobId,
    token: accessToken,
    enabled: true,
  });

  const lastEvent = events.length > 0 ? events[events.length - 1] : undefined;
  const hasFailed = lastEvent?.status === "failed";

  const {
    data: decision,
    isError: isResultError,
    error: resultError,
  } = useAnalysisResult({ jobId, accessToken, enabled: isComplete && !hasFailed });

  const {
    data: chartData,
    isError: isChartsError,
    error: chartsError,
  } = useAnalysisCharts({ jobId, accessToken, enabled: isComplete && !hasFailed });

  const hasReportedRef = useRef(false);

  useEffect(() => {
    if (hasReportedRef.current || !isComplete) {
      return;
    }
    if (hasFailed || isResultError || isChartsError) {
      hasReportedRef.current = true;
      onSettled(null);
      return;
    }
    if (decision && chartData) {
      hasReportedRef.current = true;
      onSettled({ decision, charts: chartData });
    }
  }, [isComplete, hasFailed, isResultError, isChartsError, decision, chartData, onSettled]);

  return (
    <Card data-testid="company-analysis-panel">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>

      <div className="mt-4">
        <ProgressBar
          value={isComplete ? 100 : progressPercent}
          label={connectionStatus === "connecting" ? "Connecting…" : "Progress"}
        />
      </div>

      {!isComplete ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted">
          <Spinner size="sm" aria-hidden="true" />
          {lastEvent
            ? `Last update: ${lastEvent.agent.replace(/_/g, " ")}`
            : "Waiting for the committee to start…"}
        </div>
      ) : null}

      {error ? (
        <p className="mt-3 text-xs text-verdict-sell" role="alert">
          {error}
        </p>
      ) : null}

      {isComplete && hasFailed ? (
        <p className="mt-3 text-xs text-verdict-sell" role="alert">
          {lastEvent?.output_preview || "This analysis did not complete."}
        </p>
      ) : null}

      {isComplete && !hasFailed && (isResultError || isChartsError) ? (
        <p className="mt-3 text-xs text-verdict-sell" role="alert">
          {(resultError instanceof Error && resultError.message) ||
            (chartsError instanceof Error && chartsError.message) ||
            "Could not load this analysis. Please try again."}
        </p>
      ) : null}

      {isComplete && !hasFailed && decision && chartData ? (
        <p className="mt-3 text-xs text-muted">Analysis complete.</p>
      ) : null}
    </Card>
  );
}
