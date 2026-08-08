// frontend/src/api/accuracy.ts
// AIRP -- Accuracy API client (T-092)
//
// Thin fetch wrappers around backend/routers/accuracy.py's two public
// read endpoints:
//   - GET /api/v1/accuracy/summary  (T-091) -- fetchAccuracySummary
//   - GET /api/v1/accuracy/history  (T-091) -- fetchAccuracyHistory
//
// Unlike every function in src/api/analysis.ts, neither call here sends
// an Authorization header -- backend.routers.accuracy's module docstring
// documents both routes as intentionally public (no
// Depends(get_current_user) and no Depends(verify_service_token)):
// verdict_outcomes is a platform-wide statistic, not scoped to a user,
// and AccuracyPage.tsx (this task) is the public dashboard that spec
// calls for. A caller does not need to be signed in, and does not pass
// an accessToken to either function below.
//
// AccuracyApiError and parseErrorDetail intentionally duplicate
// src/api/analysis.ts's AnalysisApiError/parseErrorDetail (which itself
// duplicates src/api/auth.ts's pair) rather than sharing one
// implementation -- small enough that keeping each API client
// independently readable outweighs a shared abstraction for three call
// sites, the same tradeoff analysis.ts's own docstring documents.

import { env } from "@/config/env";
import { type AccuracyHistoryResponse, type AccuracySummaryResponse } from "@/types/accuracy";

export class AccuracyApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AccuracyApiError";
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

// ---------------------------------------------------------------------------
// GET /api/v1/accuracy/summary (T-091, consumed by AccuracySummaryStats)
// ---------------------------------------------------------------------------

/**
 * GET /api/v1/accuracy/summary -- overall accuracy percentage plus
 * breakdowns by verdict type and conviction-score bucket. No parameters:
 * the endpoint always returns the platform's complete, current picture.
 */
export async function fetchAccuracySummary(): Promise<AccuracySummaryResponse> {
  const response = await fetch(`${env.apiBaseUrl}/accuracy/summary`, { method: "GET" });

  if (!response.ok) {
    throw new AccuracyApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as AccuracySummaryResponse;
}

// ---------------------------------------------------------------------------
// GET /api/v1/accuracy/history (T-091, consumed by the trend/scatter charts)
// ---------------------------------------------------------------------------

export interface FetchAccuracyHistoryParams {
  limit?: number;
  offset?: number;
}

/**
 * GET /api/v1/accuracy/history?limit=&offset=, newest verdict first.
 *
 * `limit`/`offset` are forwarded as-is; the backend clamps them to
 * `[1, MAX_ACCURACY_HISTORY_PAGE_SIZE]` / `>= 0` itself
 * (backend.routers.accuracy.get_accuracy_history_endpoint's
 * `Query(ge=..., le=...)` validation), so this client does not duplicate
 * that range-checking -- the same reasoning fetchAnalysisHistory's own
 * docstring already applies to the equivalent user-scoped endpoint.
 */
export async function fetchAccuracyHistory({
  limit,
  offset,
}: FetchAccuracyHistoryParams = {}): Promise<AccuracyHistoryResponse> {
  const query = new URLSearchParams();
  if (limit !== undefined) {
    query.set("limit", String(limit));
  }
  if (offset !== undefined) {
    query.set("offset", String(offset));
  }
  const queryString = query.toString();

  const response = await fetch(
    `${env.apiBaseUrl}/accuracy/history${queryString ? `?${queryString}` : ""}`,
    { method: "GET" },
  );

  if (!response.ok) {
    throw new AccuracyApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as AccuracyHistoryResponse;
}
