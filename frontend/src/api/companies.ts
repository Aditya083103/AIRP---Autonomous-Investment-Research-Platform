// frontend/src/api/companies.ts
// AIRP -- Company search API client (B5)
//
// Thin fetch wrapper around backend/routers/companies.py:
//   - GET /api/v1/companies/search -- searchCompanies
//
// CompanyApiError and parseErrorDetail intentionally duplicate
// src/api/chat.ts's ChatApiError/parseErrorDetail rather than sharing
// one implementation -- the same tradeoff that file's own docstring
// (and every other API client in this codebase) already makes.

import { env } from "@/config/env";
import { type CompanySearchResponse } from "@/types/company";

export class CompanyApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "CompanyApiError";
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

export interface SearchCompaniesParams {
  accessToken: string;
  query: string;
  limit?: number;
  offset?: number;
}

/**
 * GET /api/v1/companies/search.
 *
 * Ranked, paginated company search over the backend's curated NSE
 * universe -- see backend.services.company_search's own docstring for
 * the ranking rules. Callers (CompanyAutocomplete) are expected to
 * catch a thrown CompanyApiError and degrade to the static
 * frontend/src/data/nseTop50.ts fallback rather than surface a raw
 * error to the person mid-search -- a transient network blip should
 * never block picking a well-known top-50 company.
 */
export async function searchCompanies({
  accessToken,
  query,
  limit,
  offset,
}: SearchCompaniesParams): Promise<CompanySearchResponse> {
  const params = new URLSearchParams();
  if (query.length > 0) params.set("q", query);
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const queryString = params.toString();

  const response = await fetch(
    `${env.apiBaseUrl}/companies/search${queryString ? `?${queryString}` : ""}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );

  if (!response.ok) {
    throw new CompanyApiError(response.status, await parseErrorDetail(response));
  }
  return (await response.json()) as CompanySearchResponse;
}
