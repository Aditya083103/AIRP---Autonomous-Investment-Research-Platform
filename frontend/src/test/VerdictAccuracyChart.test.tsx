// frontend/src/test/VerdictAccuracyChart.test.tsx
// Tests for VerdictAccuracyChart (T-092). Same lightweight approach as
// PeerValuationChart.test.tsx / RevenueProfitChart.test.tsx.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerdictAccuracyChart } from "@/components/charts/VerdictAccuracyChart";
import { type VerdictAccuracyBreakdownResponse } from "@/types/accuracy";

const SAMPLE_BREAKDOWN: VerdictAccuracyBreakdownResponse[] = [
  { verdict: "BUY", evaluated_count: 5, correct_count: 4, accuracy_pct: 80.0 },
  { verdict: "HOLD", evaluated_count: 3, correct_count: 2, accuracy_pct: 66.67 },
  { verdict: "SELL", evaluated_count: 2, correct_count: 1, accuracy_pct: 50.0 },
];

const UNSCORED_BREAKDOWN: VerdictAccuracyBreakdownResponse[] = [
  { verdict: "BUY", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
  { verdict: "HOLD", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
  { verdict: "SELL", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
];

describe("VerdictAccuracyChart", () => {
  it("renders the chart title", () => {
    render(<VerdictAccuracyChart byVerdict={SAMPLE_BREAKDOWN} />);
    expect(screen.getByText("Accuracy by verdict type")).toBeInTheDocument();
  });

  it("renders the chart container when breakdown data is present", () => {
    render(<VerdictAccuracyChart byVerdict={SAMPLE_BREAKDOWN} />);
    expect(screen.getByTestId("verdict-accuracy-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when byVerdict is empty", () => {
    render(<VerdictAccuracyChart byVerdict={[]} />);
    expect(screen.getByText("Verdict accuracy data was not available.")).toBeInTheDocument();
  });

  it("shows a not-yet-scored note when every verdict has zero evaluated rows", () => {
    render(<VerdictAccuracyChart byVerdict={UNSCORED_BREAKDOWN} />);
    expect(screen.getByText(/no verdicts have been scored yet for any type/i)).toBeInTheDocument();
  });

  it("does not show the not-yet-scored note once at least one verdict has data", () => {
    render(<VerdictAccuracyChart byVerdict={SAMPLE_BREAKDOWN} />);
    expect(
      screen.queryByText(/no verdicts have been scored yet for any type/i),
    ).not.toBeInTheDocument();
  });
});
