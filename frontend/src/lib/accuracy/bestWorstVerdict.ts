// frontend/src/lib/accuracy/bestWorstVerdict.ts
// AIRP -- best/worst verdict-type computation (B11)
//
// B11 names "best/worst verdict type" as one of the Accuracy page's
// desired KPIs, alongside the overall accuracy/scored/awaiting stats
// AccuracySummaryStats.tsx (T-092) already shows and the per-verdict
// breakdown VerdictAccuracyChart.tsx already charts. This is the same
// summary.by_verdict data VerdictAccuracyChart already reads --
// AccuracySummaryStats.tsx being the KPI-tile layer, this just picks
// the highest/lowest accuracy_pct out of it for a text-level answer to
// "which verdict type has the committee been best/worst at", rather
// than requiring the visitor to eyeball three bars.
//
// A verdict with accuracy_pct === null (zero evaluated rows yet, see
// VerdictAccuracyBreakdownResponse's own docstring) is excluded from
// consideration entirely -- an unscored verdict is not "the worst",
// it is simply unknown, the same null-vs.-zero distinction this
// codebase already draws everywhere else accuracy_pct appears.

import { type VerdictAccuracyBreakdownResponse } from "@/types/accuracy";
import { type Verdict } from "@/types/analysis";

export interface ScoredVerdictAccuracy {
  verdict: Verdict;
  accuracy_pct: number;
  evaluated_count: number;
}

export interface BestWorstVerdict {
  best: ScoredVerdictAccuracy | null;
  worst: ScoredVerdictAccuracy | null;
}

function toScored(entry: VerdictAccuracyBreakdownResponse): ScoredVerdictAccuracy | null {
  if (entry.accuracy_pct === null) {
    return null;
  }
  return {
    verdict: entry.verdict,
    accuracy_pct: entry.accuracy_pct,
    evaluated_count: entry.evaluated_count,
  };
}

/**
 * Picks the highest- and lowest-accuracy verdict types out of a
 * by_verdict breakdown, ignoring any verdict with zero evaluated rows.
 * Both are null when nothing has been scored yet; both are the SAME
 * entry when exactly one verdict type has been scored so far -- that is
 * still an honest answer ("BUY is both the best and worst so far,
 * because it's the only one scored"), not a bug to special-case away.
 */
export function computeBestWorstVerdict(
  byVerdict: VerdictAccuracyBreakdownResponse[],
): BestWorstVerdict {
  const scored = byVerdict
    .map(toScored)
    .filter((entry): entry is ScoredVerdictAccuracy => entry !== null);

  if (scored.length === 0) {
    return { best: null, worst: null };
  }

  const best = scored.reduce((current, candidate) =>
    candidate.accuracy_pct > current.accuracy_pct ? candidate : current,
  );
  const worst = scored.reduce((current, candidate) =>
    candidate.accuracy_pct < current.accuracy_pct ? candidate : current,
  );

  return { best, worst };
}
