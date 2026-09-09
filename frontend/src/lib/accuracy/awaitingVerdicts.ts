// frontend/src/lib/accuracy/awaitingVerdicts.ts
// AIRP -- awaiting-verdict scheduling computation (B7)
//
// Pure, framework-free transform from a page of AccuracyHistoryEntryResponse
// rows into the still-pending subset, each carrying its scheduled scoring
// date (verdict_date + evaluation_horizon_days). A verdict only gets a
// directional_correct once backend.services.accuracy_tracker's
// run_due_evaluations reaches its evaluation_horizon_days, so a visitor
// landing on a mostly-pending accuracy dashboard sees nothing scored and no
// indication anything is happening. Surfacing *when* each pending verdict
// will be scored is proof the pipeline is alive, not broken -- the same
// "directional_correct === null means pending" rule
// rollingAccuracy.ts's docstring already documents, applied in the
// opposite direction: rollingAccuracy.ts discards pending rows because
// they have no correctness to plot yet; this file exists specifically to
// surface those discarded rows on their own terms (see
// AwaitingVerdictsCard.tsx, this computation's only caller).

import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";
import { type Verdict } from "@/types/analysis";

export interface AwaitingVerdict {
  id: string;
  ticker: string;
  verdict: Verdict;
  conviction_score: number;
  /** ISO timestamp: verdict_date + evaluation_horizon_days. */
  scheduled_scoring_date: string;
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** verdict_date + evaluation_horizon_days, as an ISO timestamp string. */
export function computeScheduledScoringDate(
  verdictDate: string,
  evaluationHorizonDays: number,
): string {
  const scheduled = new Date(new Date(verdictDate).getTime() + evaluationHorizonDays * MS_PER_DAY);
  return scheduled.toISOString();
}

/**
 * Extracts still-pending entries (directional_correct === null) from a page
 * of accuracy history, each carrying its computed scheduled_scoring_date,
 * soonest-scheduled first -- so a visitor sees the verdict due to be scored
 * *next* at the top, not an arbitrary order.
 */
export function getAwaitingVerdicts(entries: AccuracyHistoryEntryResponse[]): AwaitingVerdict[] {
  const pending = entries
    .filter((entry) => entry.directional_correct === null)
    .map((entry) => ({
      id: entry.id,
      ticker: entry.ticker,
      verdict: entry.verdict,
      conviction_score: entry.conviction_score,
      scheduled_scoring_date: computeScheduledScoringDate(
        entry.verdict_date,
        entry.evaluation_horizon_days,
      ),
    }));

  return pending.sort(
    (a, b) =>
      new Date(a.scheduled_scoring_date).getTime() - new Date(b.scheduled_scoring_date).getTime(),
  );
}
