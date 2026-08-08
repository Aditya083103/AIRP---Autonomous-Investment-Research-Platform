// frontend/src/test/ConvictionAccuracyScatterChart.test.tsx
// Tests for ConvictionAccuracyScatterChart (T-092). Same lightweight
// approach as the other T-092/T-062 chart tests.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConvictionAccuracyScatterChart } from "@/components/charts/ConvictionAccuracyScatterChart";
import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";

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

describe("ConvictionAccuracyScatterChart", () => {
  it("renders the chart title", () => {
    render(<ConvictionAccuracyScatterChart entries={[makeEntry()]} />);
    expect(screen.getByText("Conviction vs. outcome")).toBeInTheDocument();
  });

  it("renders the chart container when at least one evaluated entry exists", () => {
    render(<ConvictionAccuracyScatterChart entries={[makeEntry()]} />);
    expect(screen.getByTestId("conviction-accuracy-scatter-chart")).toBeInTheDocument();
  });

  it("renders the chart when there are only incorrect entries", () => {
    render(
      <ConvictionAccuracyScatterChart
        entries={[makeEntry({ directional_correct: false, price_change_pct: -8.2 })]}
      />,
    );
    expect(screen.getByTestId("conviction-accuracy-scatter-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when no entries have been evaluated yet", () => {
    render(
      <ConvictionAccuracyScatterChart
        entries={[
          makeEntry({
            directional_correct: null,
            price_change_pct: null,
            evaluated_at: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });

  it("shows a fallback message for a completely empty entries array", () => {
    render(<ConvictionAccuracyScatterChart entries={[]} />);
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });

  it("excludes entries with a null price_change_pct even if directional_correct is set", () => {
    // Defensive case: should not occur in practice (the backend sets both
    // together), but the component must not crash on it.
    render(<ConvictionAccuracyScatterChart entries={[makeEntry({ price_change_pct: null })]} />);
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });
});
