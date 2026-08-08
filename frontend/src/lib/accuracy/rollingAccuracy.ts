// frontend/src/lib/accuracy/rollingAccuracy.ts
// AIRP -- rolling accuracy trend computation (T-092)
//
// Pure, framework-free transform from a page of
// AccuracyHistoryEntryResponse rows (GET /api/v1/accuracy/history, T-091)
// into the rolling-window accuracy series AccuracyTrendChart.tsx plots.
// Kept out of the chart component itself, the same "computation
// separate from rendering" split src/lib/compare/winnerLogic.ts already
// establishes for ComparisonTable -- it lets this file be unit-tested
// with plain arrays of fixtures, no React Testing Library or Recharts
// involved at all.
//
// Why a ROLLING window, not cumulative-to-date accuracy
// -------------------------------------------------------------------
// A cumulative "accuracy of every verdict ever scored, as of this point
// in time" line only ever moves slowly and monotonically converges --
// after a few hundred scored verdicts, one more correct or incorrect
// call barely nudges it, so the line stops being informative about
// whether the committee is *currently* performing well or has drifted.
// A rolling window over the last ROLLING_WINDOW_SIZE evaluated verdicts
// stays responsive to recent performance instead, at the cost of some
// noise while very few verdicts have been scored -- which is exactly
// why `sample_size` is carried alongside every point (see
// RollingAccuracyPoint below): AccuracyTrendChart's tooltip can show it
// so an early, small-sample point on the line is never mistaken for a
// stable trend.
//
// Only EVALUATED entries participate
// -------------------------------------------------------------------
// `directional_correct` is `null` for a verdict_outcomes row that has
// not reached its evaluation_horizon_days yet (T-089's "pending" state,
// documented on AccuracyHistoryEntryResponse). A pending row has no
// correctness to contribute to any window, so it is filtered out before
// windowing rather than being treated as neither a hit nor a miss inside
// the window -- counting it either way would silently understate the
// rolling accuracy for whichever direction "counts as wrong" happened to
// be chosen.

import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";

/** Number of most-recent evaluated verdicts averaged into each rolling-window point. */
export const ROLLING_WINDOW_SIZE = 10;

export interface RollingAccuracyPoint {
  /** ISO timestamp of the verdict at this point (AccuracyHistoryEntryResponse.verdict_date). */
  verdict_date: string;
  /** Percentage of the window's verdicts that were directionally correct, 0-100. */
  rolling_accuracy_pct: number;
  /** How many evaluated verdicts fed this point -- fewer than windowSize near the start. */
  sample_size: number;
}

/**
 * Build a chronological (oldest-first) rolling-accuracy series from a
 * page of accuracy history entries, for AccuracyTrendChart's line chart.
 *
 * Entries with `directional_correct === null` (still pending evaluation)
 * are dropped before windowing -- see this file's docstring. The
 * remaining entries are sorted oldest-to-newest by `verdict_date`
 * (GET /api/v1/accuracy/history itself returns newest-first, matching a
 * "most recent activity at the top" list; a left-to-right trend line
 * needs the opposite order). Each returned point's window is the
 * `windowSize` most recent evaluated verdicts AT OR BEFORE that point --
 * so the first point in a data set smaller than `windowSize` is a
 * window of 1, the second a window of 2, and so on, until the window
 * reaches its full size and then slides.
 *
 * @param entries    A page of AccuracyHistoryEntryResponse rows, any order.
 * @param windowSize Rolling window width. Defaults to ROLLING_WINDOW_SIZE.
 * @returns          Oldest-first RollingAccuracyPoint[]. Empty when no
 *                   entry in `entries` has been evaluated yet.
 */
export function buildRollingAccuracySeries(
  entries: AccuracyHistoryEntryResponse[],
  windowSize: number = ROLLING_WINDOW_SIZE,
): RollingAccuracyPoint[] {
  const evaluated = entries.filter((entry) => entry.directional_correct !== null);

  const chronological = [...evaluated].sort(
    (a, b) => new Date(a.verdict_date).getTime() - new Date(b.verdict_date).getTime(),
  );

  return chronological.map((current, index) => {
    const windowStart = Math.max(0, index - windowSize + 1);
    const window = chronological.slice(windowStart, index + 1);
    const correctCount = window.filter((entry) => entry.directional_correct === true).length;

    return {
      verdict_date: current.verdict_date,
      rolling_accuracy_pct: Math.round((correctCount / window.length) * 10000) / 100,
      sample_size: window.length,
    };
  });
}
