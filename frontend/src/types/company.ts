// frontend/src/types/company.ts
// AIRP -- Company search types (B5)
//
// Mirrors backend.models.schemas's CompanySearchResultResponse /
// CompanySearchResponse field-for-field, the same "wire shape and
// TypeScript type stay identical" convention every other src/types/*
// file in this codebase already follows.

/** One ranked company search result. Mirrors CompanySearchResultResponse. */
export interface CompanySearchResult {
  name: string;
  ticker: string;
  exchange: "NSE" | "BSE";
}

/** Body returned by GET /api/v1/companies/search. Mirrors CompanySearchResponse. */
export interface CompanySearchResponse {
  items: CompanySearchResult[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}
