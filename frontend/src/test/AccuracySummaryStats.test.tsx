// frontend/src/test/AccuracySummaryStats.test.tsx
// Tests for AccuracySummaryStats (T-092, B11): the 5-tile overview row.
// Stubs prefers-reduced-motion to `true` throughout -- AnimatedNumber
// counts up from 0 on mount when motion is allowed (see that
// component's own tests), which would make a synchronous
// getByText("70.0%") assertion here flaky; this file's job is
// confirming the *right numbers* are wired in, not re-testing
// AnimatedNumber's own animation.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccuracySummaryStats } from "@/components/charts/AccuracySummaryStats";
import { type AccuracySummaryResponse } from "@/types/accuracy";

function stubReducedMotion(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

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
    by_conviction: [],
    ...overrides,
  };
}

beforeEach(() => {
  stubReducedMotion();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it("renders all five tile labels", () => {
    render(<AccuracySummaryStats summary={makeSummary()} />);
    expect(screen.getByText("Overall accuracy")).toBeInTheDocument();
    expect(screen.getByText("Verdicts scored")).toBeInTheDocument();
    expect(screen.getByText("Awaiting evaluation")).toBeInTheDocument();
    expect(screen.getByText("Best verdict type")).toBeInTheDocument();
    expect(screen.getByText("Worst verdict type")).toBeInTheDocument();
  });

  it("renders the best and worst verdict types with their accuracy percentages", () => {
    render(<AccuracySummaryStats summary={makeSummary()} />);
    // BUY (80%) is best, SELL (50%) is worst, per makeSummary's fixture.
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("80.0%")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
  });

  it("shows placeholder dashes for best/worst verdict when nothing has been scored yet", () => {
    render(
      <AccuracySummaryStats
        summary={makeSummary({
          by_verdict: [
            { verdict: "BUY", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
            { verdict: "HOLD", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
            { verdict: "SELL", evaluated_count: 0, correct_count: 0, accuracy_pct: null },
          ],
        })}
      />,
    );
    // 2 placeholders here plus 1 for the overall-accuracy tile in other
    // tests -- this fixture keeps overall_accuracy_pct at its default
    // 70.0, so exactly 2 dashes (best, worst) are expected.
    expect(screen.getAllByText("--")).toHaveLength(2);
  });
});
