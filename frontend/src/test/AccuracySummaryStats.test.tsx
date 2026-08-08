// frontend/src/test/AccuracySummaryStats.test.tsx
// Tests for AccuracySummaryStats (T-092): the 3-tile overview row.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AccuracySummaryStats } from "@/components/charts/AccuracySummaryStats";
import { type AccuracySummaryResponse } from "@/types/accuracy";

function makeSummary(overrides: Partial<AccuracySummaryResponse> = {}): AccuracySummaryResponse {
  return {
    total_evaluated: 10,
    total_pending: 2,
    overall_accuracy_pct: 70.0,
    by_verdict: [],
    by_conviction: [],
    ...overrides,
  };
}

describe("AccuracySummaryStats", () => {
  it("renders the container", () => {
    render(<AccuracySummaryStats summary={makeSummary()} />);
    expect(screen.getByTestId("accuracy-summary-stats")).toBeInTheDocument();
  });

  it("renders the overall accuracy percentage formatted to one decimal place", () => {
    render(<AccuracySummaryStats summary={makeSummary({ overall_accuracy_pct: 70 })} />);
    expect(screen.getByText("70.0%")).toBeInTheDocument();
  });

  it("renders total_evaluated and total_pending as localised counts", () => {
    render(
      <AccuracySummaryStats summary={makeSummary({ total_evaluated: 1234, total_pending: 5 })} />,
    );
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("shows a placeholder dash instead of a percentage when overall_accuracy_pct is null", () => {
    render(<AccuracySummaryStats summary={makeSummary({ overall_accuracy_pct: null })} />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });

  it("renders all three tile labels", () => {
    render(<AccuracySummaryStats summary={makeSummary()} />);
    expect(screen.getByText("Overall accuracy")).toBeInTheDocument();
    expect(screen.getByText("Verdicts scored")).toBeInTheDocument();
    expect(screen.getByText("Awaiting evaluation")).toBeInTheDocument();
  });
});
