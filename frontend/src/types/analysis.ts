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

/**
 * Mirrors backend.models.schemas.AnalysisStartResponse (T-047/T-058).
 * Returned by POST /api/v1/analysis/start the moment the job is
 * created -- before any agent has run.
 */
export interface AnalysisStartResponse {
  job_id: string;
  status: AnalysisStatus;
  company_name: string;
  ticker: string;
  exchange: string;
}

/**
 * Mirrors backend.models.schemas.DocumentUploadResponse (T-051/T-058).
 * Returned by POST /api/v1/documents/upload.
 */
export interface DocumentUploadResponse {
  company_name: string;
  ticker: string;
  exchange: string;
  source_filename: string;
  doc_type: string;
  chunks_ingested: number;
}

/**
 * Mirrors backend.models.schemas.InvestmentDecisionResponse (T-050
 * backend / T-061 frontend). Returned by GET
 * /api/v1/analysis/{job_id}/result -- field-for-field identical to the
 * Portfolio Manager agent's InvestmentDecision output, round-tripped
 * through analyses.state_snapshot with no further computation on the
 * backend, so this type does not add any field the backend router
 * doesn't already guarantee.
 */
export interface InvestmentDecisionResponse {
  /** Always "portfolio_manager" -- the agent that produced this decision. */
  agent_name: string;
  /** UUID of the parent Analysis job, as a string -- same value as the route's job_id. */
  analysis_id: string;
  company_name: string;
  ticker: string;
  /** ISO-8601 UTC timestamp string. */
  generated_at: string;
  /** Always null for a result this endpoint returns; kept for schema parity. */
  error: string | null;

  verdict: Verdict;
  /** Portfolio Manager confidence in the verdict, 1-10. */
  conviction_score: number;
  /** Implied price target (e.g. "₹4,200 (12-month)"), or null if inconclusive. */
  price_target: string | null;
  /** Suggested holding period for this verdict, e.g. "12 months". */
  time_horizon: string;

  executive_summary: string;
  investment_thesis: string;
  bull_case: string;
  bear_case: string;
  risk_summary: string;
  valuation_summary: string;

  /** Structured top risks, critical Risk Officer flags first, capped at 6. */
  key_risks: string[];
  /** Structured factors that could move the thesis forward, capped at 5. */
  key_catalysts: string[];

  /** How the Portfolio Manager addressed the Contrarian's strongest argument. */
  contrarian_response: string;
  /** Number of agent debate rounds completed before this decision. */
  debate_rounds_used: number;
  /** Weight (0.0-1.0) assigned to each agent's output, keyed by agent_name. */
  agent_weights: Record<string, number>;
  /** One-sentence summary suitable for dashboard display. */
  summary: string;
}
