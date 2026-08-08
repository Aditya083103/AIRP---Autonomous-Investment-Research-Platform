// frontend/src/types/accuracy.ts
// TypeScript types mirroring backend.models.schemas' T-091 accuracy models
// exactly -- same snake_case-preserving convention src/types/analysis.ts
// already established, so a response can be trusted as-is without a
// separate camelCase remapping step that could silently drift from the
// backend schema over time.
//
// Unlike everything in src/types/analysis.ts, none of these shapes are
// scoped to a job_id or a logged-in user -- GET /api/v1/accuracy/summary
// and GET /api/v1/accuracy/history (T-091) are both public, platform-wide
// endpoints (see backend/routers/accuracy.py's module docstring), which
// is why AccuracyHistoryEntryResponse carries its own analysis_id rather
// than being nested under an existing per-analysis type.

import { type Verdict } from "@/types/analysis";

/**
 * Mirrors backend.models.schemas.VerdictAccuracyBreakdownResponse. One
 * entry of AccuracySummaryResponse.by_verdict -- always exactly one row
 * per BUY/HOLD/SELL, even for a verdict with zero scored rows so far.
 */
export interface VerdictAccuracyBreakdownResponse {
  verdict: Verdict;
  evaluated_count: number;
  correct_count: number;
  /** Null (not 0) when evaluated_count is 0 -- an unscored verdict has unknown accuracy. */
  accuracy_pct: number | null;
}

/** Machine-readable conviction-score bucket key -- see ConvictionAccuracyBreakdownResponse. */
export type ConvictionBucket = "low" | "medium" | "high";

/**
 * Mirrors backend.models.schemas.ConvictionAccuracyBreakdownResponse. One
 * entry of AccuracySummaryResponse.by_conviction -- always exactly one
 * row per low (1-3) / medium (4-6) / high (7-10) bucket.
 */
export interface ConvictionAccuracyBreakdownResponse {
  bucket: ConvictionBucket;
  label: string;
  min_score: number;
  max_score: number;
  evaluated_count: number;
  correct_count: number;
  /** Null (not 0) when evaluated_count is 0 -- an unscored bucket has unknown accuracy. */
  accuracy_pct: number | null;
}

/** Mirrors backend.models.schemas.AccuracySummaryResponse. Body of GET /api/v1/accuracy/summary. */
export interface AccuracySummaryResponse {
  total_evaluated: number;
  total_pending: number;
  /** Null (not 0) when total_evaluated is 0 -- see the two breakdown types' own docstrings. */
  overall_accuracy_pct: number | null;
  /** Always exactly 3 entries -- BUY, HOLD, SELL, in that order. */
  by_verdict: VerdictAccuracyBreakdownResponse[];
  /** Always exactly 3 entries -- low, medium, high, in that order. */
  by_conviction: ConvictionAccuracyBreakdownResponse[];
}

/**
 * Mirrors backend.models.schemas.AccuracyHistoryEntryResponse. One row of
 * GET /api/v1/accuracy/history's paginated result -- one verdict_outcomes
 * row, evaluated or still pending.
 */
export interface AccuracyHistoryEntryResponse {
  id: string;
  analysis_id: string;
  ticker: string;
  verdict: Verdict;
  conviction_score: number;
  price_at_verdict: number;
  verdict_date: string;
  evaluation_horizon_days: number;
  /** Null until run_due_evaluations (T-089) scores this row. */
  price_at_evaluation: number | null;
  /** Null until evaluated. */
  price_change_pct: number | null;
  /** Null until evaluated. */
  directional_correct: boolean | null;
  /** Null until evaluated. */
  evaluated_at: string | null;
}

/** Mirrors backend.models.schemas.AccuracyHistoryResponse. Body of GET /api/v1/accuracy/history. */
export interface AccuracyHistoryResponse {
  items: AccuracyHistoryEntryResponse[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
