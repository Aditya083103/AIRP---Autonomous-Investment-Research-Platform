// frontend/src/types/analysis.ts
// TypeScript types mirroring backend.models.schemas' history models
// exactly (T-050 backend / T-057 frontend) -- same snake_case-preserving
// convention src/types/auth.ts and useAnalysisStream.ts's
// AgentStreamEvent already use, so a response can be trusted as-is
// without a separate camelCase remapping step that could silently drift
// from the backend schema over time.

/** Lifecycle status of an analysis job, as stored in analyses.status. */
export type AnalysisStatus = "pending" | "running" | "completed" | "failed";

/** Final verdict once a pipeline finishes -- null until then. */
export type Verdict = "BUY" | "HOLD" | "SELL";

/**
 * Mirrors backend.models.schemas.HistoryEntryResponse. One row of
 * GET /api/v1/analysis/history.
 */
export interface HistoryEntryResponse {
  job_id: string;
  company_name: string;
  ticker: string;
  exchange: string;
  status: AnalysisStatus;
  requested_at: string;
  completed_at: string | null;
  verdict: Verdict | null;
  conviction_score: number | null;
}

/** Mirrors backend.models.schemas.HistoryResponse. */
export interface HistoryResponse {
  items: HistoryEntryResponse[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
