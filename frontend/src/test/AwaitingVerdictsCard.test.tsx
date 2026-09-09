// frontend/src/test/AwaitingVerdictsCard.test.tsx
// Tests for AwaitingVerdictsCard (B7): the scheduled-scoring-date list.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AwaitingVerdictsCard } from "@/components/charts/AwaitingVerdictsCard";
import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";

function makeEntry(
  overrides: Partial<AccuracyHistoryEntryResponse> = {},
): AccuracyHistoryEntryResponse {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    analysis_id: "22222222-2222-2222-2222-222222222222",
    ticker: "TCS.NS",
    verdict: "BUY",
    conviction_score: 7,
    price_at_verdict: 3000.0,
    verdict_date: "2026-01-01T00:00:00Z",
    evaluation_horizon_days: 90,
    price_at_evaluation: null,
    price_change_pct: null,
    directional_correct: null,
    evaluated_at: null,
    ...overrides,
  };
}

describe("AwaitingVerdictsCard", () => {
  it("renders the container", () => {
    render(<AwaitingVerdictsCard entries={[]} />);
    expect(screen.getByTestId("awaiting-verdicts-card")).toBeInTheDocument();
  });

  it("shows a friendly message when nothing is awaiting evaluation", () => {
    const evaluated = makeEntry({
      directional_correct: true,
      price_at_evaluation: 3200.0,
      price_change_pct: 6.6667,
      evaluated_at: "2026-04-01T00:00:00Z",
    });

    render(<AwaitingVerdictsCard entries={[evaluated]} />);

    expect(screen.getByText(/nothing is currently awaiting evaluation/i)).toBeInTheDocument();
  });

  it("renders a pending entry's ticker, verdict, and scheduled scoring date", () => {
    const pending = makeEntry({
      ticker: "INFY.NS",
      verdict: "HOLD",
      verdict_date: "2026-01-01T00:00:00.000Z",
      evaluation_horizon_days: 30,
    });

    render(<AwaitingVerdictsCard entries={[pending]} />);

    expect(screen.getByText("INFY.NS")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByText(/scored on 31 jan 2026/i)).toBeInTheDocument();
  });

  it("caps visible rows at MAX_VISIBLE_AWAITING and shows a +N more line", () => {
    const entries = Array.from({ length: 10 }, (_, index) =>
      makeEntry({
        id: `entry-${index}`,
        ticker: `T${index}.NS`,
        verdict_date: "2026-01-01T00:00:00Z",
        evaluation_horizon_days: index + 1,
      }),
    );

    render(<AwaitingVerdictsCard entries={entries} />);

    expect(screen.getByText("T0.NS")).toBeInTheDocument();
    expect(screen.getByText(/\+2 more verdicts awaiting evaluation/i)).toBeInTheDocument();
    expect(screen.queryByText("T9.NS")).not.toBeInTheDocument();
  });
});
