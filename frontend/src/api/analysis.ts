// frontend/src/api/analysis.ts
// AIRP -- Analysis API client (T-057)
//
// Thin fetch wrapper around GET /api/v1/analysis/history
// (backend/routers/analysis.py, T-050). Unlike src/api/auth.ts, this
// endpoint authenticates via a Bearer Authorization header rather than
// the httpOnly cookie -- it is called with the in-memory accessToken
// from useAuth(), the same token useAnalysisStream.ts already needs for
// its WebSocket `?token=` parameter (see AuthProvider.tsx's docstring
// for the full reasoning on why that token lives in JS memory at all).
//
// AnalysisApiError and parseErrorDetail intentionally duplicate
// src/api/auth.ts's AuthApiError/parseErrorDetail rather than sharing
// one implementation -- small enough that keeping the two API clients
// independently readable outweighs a shared abstraction for two
// call sites, the same tradeoff backend/services/analysis.py's own
// docstring makes for its duplicated ticker-override table.

import { env } from "@/config/env";
import { type HistoryResponse } from "@/types/analysis";

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
