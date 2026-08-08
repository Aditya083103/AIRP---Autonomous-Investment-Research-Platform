// frontend/src/test/AccuracyTrendChart.test.tsx
// Tests for AccuracyTrendChart (T-092). Same lightweight approach as
// StockPriceChart.test.tsx -- focuses on the title, empty-state
// fallback, and top-level container/footnote text, rather than
// asserting on Recharts' own internal SVG output.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccuracyTrendChart } from "@/components/charts/AccuracyTrendChart";
import { ROLLING_WINDOW_SIZE } from "@/lib/accuracy/rollingAccuracy";
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

describe("AccuracyTrendChart", () => {
  it("renders the chart title", () => {
    render(<AccuracyTrendChart entries={[makeEntry()]} />);
    expect(screen.getByText("Rolling accuracy trend")).toBeInTheDocument();
  });

  it("renders the chart container when at least one evaluated entry exists", () => {
    render(<AccuracyTrendChart entries={[makeEntry()]} />);
    expect(screen.getByTestId("accuracy-trend-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when no entries have been evaluated yet", () => {
    render(
      <AccuracyTrendChart
        entries={[makeEntry({ directional_correct: null, evaluated_at: null })]}
      />,
    );
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });

  it("shows a fallback message for a completely empty entries array", () => {
    render(<AccuracyTrendChart entries={[]} />);
    expect(screen.getByText(/no verdicts have been scored yet/i)).toBeInTheDocument();
  });

  it("shows the rolling window footnote with the scored-verdict count", () => {
    render(<AccuracyTrendChart entries={[makeEntry(), makeEntry()]} />);
    expect(
      screen.getByText(new RegExp(`rolling ${ROLLING_WINDOW_SIZE}-verdict window`, "i")),
    ).toBeInTheDocument();
    expect(screen.getByText(/over 2 scored verdicts/i)).toBeInTheDocument();
  });

  it("uses singular 'verdict' in the footnote for exactly one scored entry", () => {
    render(<AccuracyTrendChart entries={[makeEntry()]} />);
    expect(screen.getByText(/over 1 scored verdict\b/i)).toBeInTheDocument();
  });
});
