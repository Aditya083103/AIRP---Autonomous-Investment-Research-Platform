// frontend/src/test/AccuracyPanel.test.tsx
// Tests for AccuracyPanel (T-092) -- the top-level composition of the
// stats row and all three T-092 charts. Each child's own test file
// already covers its individual rendering/fallback behaviour in depth
// (mirrors ChartsPanel.test.tsx's own "confirm everything is wired in,
// don't re-test internals" scope for T-062).

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccuracyPanel } from "@/components/charts/AccuracyPanel";
import { type AccuracyHistoryEntryResponse, type AccuracySummaryResponse } from "@/types/accuracy";

function makeSummary(overrides: Partial<AccuracySummaryResponse> = {}): AccuracySummaryResponse {
  return {
    total_evaluated: 10,
    total_pending: 2,
    overall_accuracy_pct: 70.0,
    by_verdict: [
      { verdict: "BUY", evaluated_count: 5, correct_count: 4, accuracy_pct: 80.0 },
      { verdict: "HOLD", evaluated_count: 3, correct_count: 2, accuracy_pct: 66.67 },
      { verdict: "SELL", evaluated_count: 2, correct_count: 1, accuracy_pct: 50.0 },
    ],
    by_conviction: [
      {
        bucket: "low",
        label: "Low (1-3)",
        min_score: 1,
        max_score: 3,
        evaluated_count: 1,
        correct_count: 0,
        accuracy_pct: 0.0,
      },
      {
        bucket: "medium",
        label: "Medium (4-6)",
        min_score: 4,
        max_score: 6,
        evaluated_count: 4,
        correct_count: 3,
        accuracy_pct: 75.0,
      },
      {
        bucket: "high",
        label: "High (7-10)",
        min_score: 7,
        max_score: 10,
        evaluated_count: 5,
        correct_count: 4,
        accuracy_pct: 80.0,
      },
    ],
    ...overrides,
  };
}

function makeEntry(
  overrides: Partial<AccuracyHistoryEntryResponse> = {},
): AccuracyHistoryEntryResponse {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    analysis_id: "22222222-2222-2222-2222-222222222222",
    ticker: "TCS.NS",
    verdict: "BUY",
    conviction_score: 8,
    price_at_verdict: 3000.0,
    verdict_date: "2026-01-01T00:00:00Z",
    evaluation_horizon_days: 90,
    price_at_evaluation: 3200.0,
    price_change_pct: 6.6667,
    directional_correct: true,
    evaluated_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

describe("AccuracyPanel", () => {
  it("renders the stats row and all three charts", () => {
    render(<AccuracyPanel summary={makeSummary()} historyEntries={[makeEntry()]} />);

    expect(screen.getByTestId("accuracy-summary-stats")).toBeInTheDocument();
    expect(screen.getByTestId("accuracy-trend-chart")).toBeInTheDocument();
    expect(screen.getByTestId("verdict-accuracy-chart")).toBeInTheDocument();
    expect(screen.getByTestId("conviction-accuracy-scatter-chart")).toBeInTheDocument();
  });

  it("still renders every chart's own empty state with no history entries", () => {
    render(<AccuracyPanel summary={makeSummary()} historyEntries={[]} />);

    expect(screen.getByTestId("accuracy-trend-chart")).toBeInTheDocument();
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });
});
