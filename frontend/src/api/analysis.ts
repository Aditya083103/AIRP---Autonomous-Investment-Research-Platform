// frontend/src/api/analysis.ts
// AIRP -- Analysis API client (T-057, extended in T-058, T-061, and T-062)
//
// Thin fetch wrappers around backend/routers/analysis.py and
// backend/routers/documents.py endpoints:
//   - GET  /api/v1/analysis/history          (T-050) -- fetchAnalysisHistory
//   - POST /api/v1/analysis/start            (T-047) -- startAnalysis
//   - POST /api/v1/documents/upload          (T-051) -- uploadDocument
//   - GET  /api/v1/analysis/{job_id}/result  (T-050) -- fetchAnalysisResult
//   - GET  /api/v1/analysis/{job_id}/charts  (T-062) -- fetchAnalysisCharts
// All five authenticate via a Bearer Authorization header rather than
// the httpOnly cookie -- called with the in-memory accessToken from
// useAuth(), the same token useAnalysisStream.ts already needs for its
// WebSocket `?token=` parameter (see AuthProvider.tsx's docstring for
// the full reasoning on why that token lives in JS memory at all).
//
// AnalysisApiError and parseErrorDetail intentionally duplicate
// src/api/auth.ts's AuthApiError/parseErrorDetail rather than sharing
// one implementation -- small enough that keeping the two API clients
// independently readable outweighs a shared abstraction for two
// call sites, the same tradeoff backend/services/analysis.py's own
// docstring makes for its duplicated ticker-override table.

import { env } from "@/config/env";
import { DEFAULT_ANALYSIS_HORIZON, type AnalysisHorizon } from "@/lib/validation/analysisSchemas";
import {
  type AnalysisChartDataResponse,
  type AnalysisStartResponse,
  type DocumentUploadResponse,
  type HistoryResponse,
  type InvestmentDecisionResponse,
} from "@/types/analysis";

export class AnalysisApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AnalysisApiError";
    this.status = status;
  }
}

interface ValidationErrorDetail {
  msg?: string;
}

function isValidationErrorDetail(value: unknown): value is ValidationErrorDetail {
  return typeof value === "object" && value !== null;
}

/** See src/api/auth.ts's parseErrorDetail for the two FastAPI error-body shapes handled here. */
async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail) && detail.length > 0 && isValidationErrorDetail(detail[0])) {
        const first = detail[0];
        if (typeof first.msg === "string") {
          return first.msg;
        }
      }
    }
  } catch {
    // Response body was not JSON -- fall through to the generic message.
  }
  return "Something went wrong. Please try again.";
}

export interface FetchAnalysisHistoryParams {
  /** Bearer token from useAuth().accessToken. Callers must not call this with a null token. */
  accessToken: string;
  limit?: number;
  offset?: number;
}

/**
 * GET /api/v1/analysis/history?limit=&offset=, newest first.
 *
 * `limit`/`offset` are forwarded as-is; the backend clamps them to
 * `[1, MAX_HISTORY_PAGE_SIZE]` / `>= 0` itself
 * (backend.routers.analysis.get_analysis_history_endpoint's
 * `Query(ge=..., le=...)` validation), so this client does not
 * duplicate that range-checking.
 */
export async function fetchAnalysisHistory({
  accessToken,
  limit,
  offset,
}: FetchAnalysisHistoryParams): Promise<HistoryResponse> {
  const query = new URLSearchParams();
  if (limit !== undefined) {
    query.set("limit", String(limit));
  }
  if (offset !== undefined) {
    query.set("offset", String(offset));
  }
  const queryString = query.toString();

  const response = await fetch(
    `${env.apiBaseUrl}/analysis/history${queryString ? `?${queryString}` : ""}`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  );

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as HistoryResponse;
}

// ---------------------------------------------------------------------------
// POST /api/v1/analysis/start (T-047, consumed by the T-058 input form)
// ---------------------------------------------------------------------------

export interface StartAnalysisParams {
  accessToken: string;
  companyName: string;
  /** Yahoo Finance ticker override, e.g. 'TCS.NS'. See AnalysisStartRequest's docstring. */
  ticker: string;
  exchange: string;
  /**
   * Analysis horizon for the Technical Analyst agent's OHLCV fetch
   * (T-085) -- one of src/lib/validation/analysisSchemas.ts's
   * ANALYSIS_HORIZONS. Defaults to "1y" (backend.models.schemas.
   * DEFAULT_ANALYSIS_PERIOD) when omitted, matching the backend's own
   * default so a caller that doesn't pass this gets the exact
   * behaviour it had before T-085.
   */
  period?: AnalysisHorizon;
}

/**
 * POST /api/v1/analysis/start. Always sends `ticker`/`exchange`
 * explicitly (from the selected NSE_TOP_50 entry) rather than leaving
 * the backend to resolve `companyName` on its own -- see
 * src/data/nseTop50.ts's docstring for why that matters: the backend's
 * name-resolution table only covers ~15 companies, but an explicit
 * ticker override skips that resolution step entirely and works for
 * all 50.
 */
export async function startAnalysis({
  accessToken,
  companyName,
  ticker,
  exchange,
  period = DEFAULT_ANALYSIS_HORIZON,
}: StartAnalysisParams): Promise<AnalysisStartResponse> {
  const response = await fetch(`${env.apiBaseUrl}/analysis/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ company_name: companyName, ticker, exchange, period }),
  });

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as AnalysisStartResponse;
}

// ---------------------------------------------------------------------------
// POST /api/v1/documents/upload (T-051, consumed by the T-058 input form)
// ---------------------------------------------------------------------------

export interface UploadDocumentParams {
  accessToken: string;
  file: File;
  companyName: string;
  ticker: string;
  exchange: string;
}

/**
 * POST /api/v1/documents/upload as multipart/form-data -- no
 * `Content-Type` header is set explicitly so the browser fills in the
 * `multipart/form-data; boundary=...` value itself (setting it by hand
 * on a FormData body is a classic bug: the boundary the browser
 * actually writes into the body would no longer match a hand-set
 * header, and the backend's multipart parser would silently see zero
 * parts). See backend/routers/documents.py's docstring for why this
 * endpoint takes form fields instead of a JSON body at all.
 */
export async function uploadDocument({
  accessToken,
  file,
  companyName,
  ticker,
  exchange,
}: UploadDocumentParams): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.set("file", file);
  formData.set("company_name", companyName);
  formData.set("ticker", ticker);
  formData.set("exchange", exchange);

  const response = await fetch(`${env.apiBaseUrl}/documents/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
  });

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as DocumentUploadResponse;
}

// ---------------------------------------------------------------------------
// GET /api/v1/analysis/{job_id}/result (T-050, consumed by the T-061 results page)
// ---------------------------------------------------------------------------

export interface FetchAnalysisResultParams {
  /** Bearer token from useAuth().accessToken. Callers must not call this with a null token. */
  accessToken: string;
  jobId: string;
}

/**
 * GET /api/v1/analysis/{job_id}/result -- the full InvestmentDecision
 * produced by the Portfolio Manager agent.
 *
 * Callers should only invoke this once the analysis stream (T-049) has
 * reported `is_final: true` with a non-failed status; the backend
 * returns 409 for a job that exists but has not reached
 * status='completed' yet (see backend/routers/analysis.py's docstring
 * on get_analysis_result_endpoint), which surfaces here as an
 * AnalysisApiError the same way any other non-2xx response does.
 */
export async function fetchAnalysisResult({
  accessToken,
  jobId,
}: FetchAnalysisResultParams): Promise<InvestmentDecisionResponse> {
  const response = await fetch(`${env.apiBaseUrl}/analysis/${jobId}/result`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as InvestmentDecisionResponse;
}

// ---------------------------------------------------------------------------
// GET /api/v1/analysis/{job_id}/charts (T-062, consumed by the charts panel)
// ---------------------------------------------------------------------------

export interface FetchAnalysisChartsParams {
  /** Bearer token from useAuth().accessToken. Callers must not call this with a null token. */
  accessToken: string;
  jobId: string;
}

/**
 * GET /api/v1/analysis/{job_id}/charts -- price history, revenue/profit
 * trend, P/E-vs-peers valuation, sentiment gauge, and risk radar data
 * for a completed analysis.
 *
 * Same "only call once the stream reports completion" contract as
 * fetchAnalysisResult -- see that function's docstring. Unlike
 * fetchAnalysisResult, a 200 response here can still have individual
 * null/empty fields (valuation, sentiment, risk, price_history,
 * financials) when the backend could not populate that one source;
 * see the response's data_warnings for which, if any. That is a
 * successful response, not an AnalysisApiError -- only a genuine
 * non-2xx (404/409/5xx) throws here.
 */
export async function fetchAnalysisCharts({
  accessToken,
  jobId,
}: FetchAnalysisChartsParams): Promise<AnalysisChartDataResponse> {
  const response = await fetch(`${env.apiBaseUrl}/analysis/${jobId}/charts`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as AnalysisChartDataResponse;
}

// ---------------------------------------------------------------------------
// GET /api/v1/analysis/{job_id}/memo/pdf (T-050 backend / T-063 frontend)
// ---------------------------------------------------------------------------

export interface FetchAnalysisMemoPdfParams {
  /** Bearer token from useAuth().accessToken. Callers must not call this with a null token. */
  accessToken: string;
  jobId: string;
}

/**
 * GET /api/v1/analysis/{job_id}/memo/pdf -- the branded Investment Memo
 * PDF for a completed analysis, as a Blob.
 *
 * Unlike a plain `<a href>` download, this endpoint requires the same
 * Bearer Authorization header every other analysis route needs (see
 * backend/routers/analysis.py's download_analysis_memo_pdf), so the
 * browser cannot fetch it via simple navigation -- the caller must
 * `fetch` it with credentials attached and turn the resulting Blob
 * into a short-lived object URL itself (see useDownloadMemoPdf.ts).
 * Returns 404 both when job_id does not exist/belong to the caller and
 * when no PDF was ever produced for a completed job (WeasyPrint
 * unavailable, feature disabled, etc.) -- see that endpoint's
 * docstring for why both cases share one response shape.
 */
export async function fetchAnalysisMemoPdf({
  accessToken,
  jobId,
}: FetchAnalysisMemoPdfParams): Promise<Blob> {
  const response = await fetch(`${env.apiBaseUrl}/analysis/${jobId}/memo/pdf`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!response.ok) {
    throw new AnalysisApiError(response.status, await parseErrorDetail(response));
  }
  return await response.blob();
}
