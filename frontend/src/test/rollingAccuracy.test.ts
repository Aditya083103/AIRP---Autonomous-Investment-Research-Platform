// frontend/src/test/rollingAccuracy.test.ts
// Tests for src/lib/accuracy/rollingAccuracy.ts (T-092). Pure-function
// tests with plain fixture arrays -- no rendering, no React Query, no
// Recharts involved -- mirroring src/test/winnerLogic.test.ts's own
// "computation separate from rendering" test style.

import { describe, expect, it } from "vitest";

import { buildRollingAccuracySeries } from "@/lib/accuracy/rollingAccuracy";
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
    price_at_evaluation: 3200.0,
    price_change_pct: 6.6667,
    directional_correct: true,
    evaluated_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

describe("buildRollingAccuracySeries", () => {
  it("returns an empty series when there are no entries at all", () => {
    expect(buildRollingAccuracySeries([])).toEqual([]);
  });

  it("excludes entries that have not been evaluated yet", () => {
    const pending = makeEntry({
      directional_correct: null,
      price_at_evaluation: null,
      price_change_pct: null,
      evaluated_at: null,
    });

    expect(buildRollingAccuracySeries([pending])).toEqual([]);
  });

  it("returns one point per evaluated entry, sorted oldest-to-newest", () => {
    const newer = makeEntry({ verdict_date: "2026-03-01T00:00:00Z" });
    const older = makeEntry({ verdict_date: "2026-01-01T00:00:00Z" });

    const series = buildRollingAccuracySeries([newer, older]);

    expect(series).toHaveLength(2);
    expect(series[0]?.verdict_date).toBe("2026-01-01T00:00:00Z");
    expect(series[1]?.verdict_date).toBe("2026-03-01T00:00:00Z");
  });

  it("computes 100% for a window of all-correct verdicts", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: true }),
      makeEntry({ verdict_date: "2026-01-02T00:00:00Z", directional_correct: true }),
    ];

    const series = buildRollingAccuracySeries(entries, 10);

    expect(series[1]?.rolling_accuracy_pct).toBe(100);
    expect(series[1]?.sample_size).toBe(2);
  });

  it("computes 0% for a window of all-incorrect verdicts", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: false }),
      makeEntry({ verdict_date: "2026-01-02T00:00:00Z", directional_correct: false }),
    ];

    const series = buildRollingAccuracySeries(entries, 10);

    expect(series[1]?.rolling_accuracy_pct).toBe(0);
  });

  it("computes a rounded percentage for a mixed window", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: true }),
      makeEntry({ verdict_date: "2026-01-02T00:00:00Z", directional_correct: false }),
      makeEntry({ verdict_date: "2026-01-03T00:00:00Z", directional_correct: true }),
    ];

    const series = buildRollingAccuracySeries(entries, 10);

    // 2 correct out of 3 = 66.666...% -> rounded to 2 decimal places.
    expect(series[2]?.rolling_accuracy_pct).toBe(66.67);
  });

  it("slides the window once it reaches windowSize, dropping the oldest entry", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: false }),
      makeEntry({ verdict_date: "2026-01-02T00:00:00Z", directional_correct: true }),
      makeEntry({ verdict_date: "2026-01-03T00:00:00Z", directional_correct: true }),
    ];

    // windowSize=2 -- the 3rd point's window is only entries 2 and 3
    // (the incorrect 1st entry has fallen out of the window).
    const series = buildRollingAccuracySeries(entries, 2);

    expect(series[2]?.sample_size).toBe(2);
    expect(series[2]?.rolling_accuracy_pct).toBe(100);
  });

  it("gives an early point a smaller sample_size than a full window", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: true }),
      makeEntry({ verdict_date: "2026-01-02T00:00:00Z", directional_correct: true }),
      makeEntry({ verdict_date: "2026-01-03T00:00:00Z", directional_correct: true }),
    ];

    const series = buildRollingAccuracySeries(entries, 10);

    expect(series[0]?.sample_size).toBe(1);
    expect(series[1]?.sample_size).toBe(2);
    expect(series[2]?.sample_size).toBe(3);
  });

  it("ignores pending entries interleaved among evaluated ones", () => {
    const entries = [
      makeEntry({ verdict_date: "2026-01-01T00:00:00Z", directional_correct: true }),
      makeEntry({
        verdict_date: "2026-01-02T00:00:00Z",
        directional_correct: null,
        price_at_evaluation: null,
        price_change_pct: null,
        evaluated_at: null,
      }),
      makeEntry({ verdict_date: "2026-01-03T00:00:00Z", directional_correct: false }),
    ];

    const series = buildRollingAccuracySeries(entries, 10);

    expect(series).toHaveLength(2);
    expect(series[1]?.rolling_accuracy_pct).toBe(50);
  });
});
