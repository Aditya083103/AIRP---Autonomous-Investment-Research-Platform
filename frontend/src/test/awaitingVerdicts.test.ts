// frontend/src/test/awaitingVerdicts.test.ts
// Tests for src/lib/accuracy/awaitingVerdicts.ts (B7). Pure-function tests
// with plain fixture arrays -- no rendering involved -- mirroring
// src/test/rollingAccuracy.test.ts's own "computation separate from
// rendering" test style.

import { describe, expect, it } from "vitest";

import { computeScheduledScoringDate, getAwaitingVerdicts } from "@/lib/accuracy/awaitingVerdicts";
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

describe("computeScheduledScoringDate", () => {
  it("adds evaluation_horizon_days to verdict_date", () => {
    expect(computeScheduledScoringDate("2026-01-01T00:00:00.000Z", 90)).toBe(
      "2026-04-01T00:00:00.000Z",
    );
  });

  it("handles a single-day horizon", () => {
    expect(computeScheduledScoringDate("2026-01-01T00:00:00.000Z", 1)).toBe(
      "2026-01-02T00:00:00.000Z",
    );
  });
});

describe("getAwaitingVerdicts", () => {
  it("returns an empty array when there are no entries at all", () => {
    expect(getAwaitingVerdicts([])).toEqual([]);
  });

  it("excludes entries that have already been evaluated", () => {
    const evaluated = makeEntry({
      directional_correct: true,
      price_at_evaluation: 3200.0,
      price_change_pct: 6.6667,
      evaluated_at: "2026-04-01T00:00:00Z",
    });

    expect(getAwaitingVerdicts([evaluated])).toEqual([]);
  });

  it("includes each pending entry with its computed scheduled_scoring_date", () => {
    const pending = makeEntry({
      id: "33333333-3333-3333-3333-333333333333",
      ticker: "INFY.NS",
      verdict: "HOLD",
      conviction_score: 5,
      verdict_date: "2026-01-01T00:00:00.000Z",
      evaluation_horizon_days: 30,
    });

    const result = getAwaitingVerdicts([pending]);

    expect(result).toEqual([
      {
        id: "33333333-3333-3333-3333-333333333333",
        ticker: "INFY.NS",
        verdict: "HOLD",
        conviction_score: 5,
        scheduled_scoring_date: "2026-01-31T00:00:00.000Z",
      },
    ]);
  });

  it("sorts pending entries by scheduled_scoring_date, soonest first", () => {
    const later = makeEntry({
      id: "later",
      verdict_date: "2026-01-01T00:00:00Z",
      evaluation_horizon_days: 90,
    });
    const sooner = makeEntry({
      id: "sooner",
      verdict_date: "2026-01-01T00:00:00Z",
      evaluation_horizon_days: 10,
    });

    const result = getAwaitingVerdicts([later, sooner]);

    expect(result.map((entry) => entry.id)).toEqual(["sooner", "later"]);
  });

  it("ignores evaluated entries interleaved among pending ones", () => {
    const pending = makeEntry({ id: "pending" });
    const evaluated = makeEntry({
      id: "evaluated",
      directional_correct: false,
      price_at_evaluation: 2900.0,
      price_change_pct: -3.3,
      evaluated_at: "2026-04-01T00:00:00Z",
    });

    const result = getAwaitingVerdicts([evaluated, pending]);

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe("pending");
  });
});
