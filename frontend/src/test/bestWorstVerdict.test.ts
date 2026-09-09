// frontend/src/test/bestWorstVerdict.test.ts
// Tests for src/lib/accuracy/bestWorstVerdict.ts (B11). Pure-function
// tests with plain fixture arrays -- mirrors src/test/rollingAccuracy.
// test.ts's own "computation separate from rendering" test style.

import { describe, expect, it } from "vitest";

import { computeBestWorstVerdict } from "@/lib/accuracy/bestWorstVerdict";
import { type VerdictAccuracyBreakdownResponse } from "@/types/accuracy";

function makeBreakdown(
  overrides: Partial<VerdictAccuracyBreakdownResponse> = {},
): VerdictAccuracyBreakdownResponse {
  return {
    verdict: "BUY",
    evaluated_count: 5,
    correct_count: 4,
    accuracy_pct: 80.0,
    ...overrides,
  };
}

describe("computeBestWorstVerdict", () => {
  it("returns null for both when the array is empty", () => {
    expect(computeBestWorstVerdict([])).toEqual({ best: null, worst: null });
  });

  it("returns null for both when every verdict is unscored (accuracy_pct null)", () => {
    const byVerdict = [
      makeBreakdown({ verdict: "BUY", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
      makeBreakdown({ verdict: "HOLD", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
      makeBreakdown({ verdict: "SELL", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
    ];
    expect(computeBestWorstVerdict(byVerdict)).toEqual({ best: null, worst: null });
  });

  it("picks the highest and lowest accuracy_pct among scored verdicts", () => {
    const byVerdict = [
      makeBreakdown({ verdict: "BUY", accuracy_pct: 80.0 }),
      makeBreakdown({ verdict: "HOLD", accuracy_pct: 66.67 }),
      makeBreakdown({ verdict: "SELL", accuracy_pct: 50.0 }),
    ];

    const { best, worst } = computeBestWorstVerdict(byVerdict);

    expect(best?.verdict).toBe("BUY");
    expect(best?.accuracy_pct).toBe(80.0);
    expect(worst?.verdict).toBe("SELL");
    expect(worst?.accuracy_pct).toBe(50.0);
  });

  it("ignores unscored verdicts interleaved among scored ones", () => {
    const byVerdict = [
      makeBreakdown({ verdict: "BUY", accuracy_pct: 80.0 }),
      makeBreakdown({ verdict: "HOLD", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
      makeBreakdown({ verdict: "SELL", accuracy_pct: 50.0 }),
    ];

    const { best, worst } = computeBestWorstVerdict(byVerdict);

    expect(best?.verdict).toBe("BUY");
    expect(worst?.verdict).toBe("SELL");
  });

  it("returns the same entry for both best and worst when only one verdict is scored", () => {
    const byVerdict = [
      makeBreakdown({ verdict: "BUY", accuracy_pct: 80.0 }),
      makeBreakdown({ verdict: "HOLD", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
      makeBreakdown({ verdict: "SELL", accuracy_pct: null, evaluated_count: 0, correct_count: 0 }),
    ];

    const { best, worst } = computeBestWorstVerdict(byVerdict);

    expect(best?.verdict).toBe("BUY");
    expect(worst?.verdict).toBe("BUY");
  });
});
