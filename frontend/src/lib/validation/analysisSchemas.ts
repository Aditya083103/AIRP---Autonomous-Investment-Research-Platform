// frontend/src/lib/validation/analysisSchemas.ts
// AIRP -- Analysis input form schema (T-058)
//
// The company field is modelled as a plain `companyTicker: string`
// (empty string = nothing selected yet), NOT as a nullable
// `{name, ticker, exchange} | null` object. That nullable-object shape
// was tried first and hit a real react-hook-form typing incompatibility:
// RHF's internal `DeepPartial<TFieldValues>` (used to type
// `defaultValues`) does not preserve a `T | null` union on an object
// field correctly, which surfaced as `defaultValues: { company: null }`
// failing to type-check against the zodResolver-inferred field type,
// and a second, harder-to-read error on `handleSubmit`. A plain string
// field has none of that trouble -- AnalysisPage.tsx looks the full
// NseCompany back up from src/data/nseTop50.ts by ticker when it needs
// the display name for the API calls.
//
// The optional PDF is validated separately in AnalysisPage.tsx via
// plain functions (isPdfFile / isPdfWithinSizeLimit), not folded into
// this schema -- a `File` object doesn't bind to react-hook-form's
// register() the way a text field does, and these two checks are
// simple enough that a couple of functions read at least as clearly as
// a `z.instanceof(File)` chain wired through a Controller for a field
// this shape.

import { z } from "zod";

// T-085 -- Analysis Horizon selector. Mirrors
// backend.tools.stock_price.VALID_PERIODS / backend.models.schemas.
// _VALID_ANALYSIS_PERIODS exactly -- keep these two lists in sync if
// either side changes.
export const ANALYSIS_HORIZONS = ["1mo", "3mo", "6mo", "1y", "3y", "5y", "10y"] as const;

export type AnalysisHorizon = (typeof ANALYSIS_HORIZONS)[number];

/** Human-readable labels for the horizon selector, keyed by AnalysisHorizon. */
export const ANALYSIS_HORIZON_LABELS: Record<AnalysisHorizon, string> = {
  "1mo": "1 month",
  "3mo": "3 months",
  "6mo": "6 months",
  "1y": "1 year",
  "3y": "3 years",
  "5y": "5 years",
  "10y": "10 years",
};

/** Default analysis horizon -- matches backend.models.schemas.DEFAULT_ANALYSIS_PERIOD. */
export const DEFAULT_ANALYSIS_HORIZON: AnalysisHorizon = "1y";

export const analysisInputSchema = z.object({
  companyTicker: z.string().min(1, "Select a company from the list."),
  // `.default(...)` means an omitted `horizon` field still parses
  // successfully as DEFAULT_ANALYSIS_HORIZON -- existing callers of
  // this schema that predate T-085 (and the tests written against
  // them) keep working unchanged.
  horizon: z.enum(ANALYSIS_HORIZONS).default(DEFAULT_ANALYSIS_HORIZON),
});

export type AnalysisInputFormValues = z.infer<typeof analysisInputSchema>;

/** Maximum accepted PDF upload size for this form, per the T-058 acceptance criterion. */
export const MAX_PDF_UPLOAD_BYTES = 10 * 1024 * 1024;

/**
 * True if `file` looks like a PDF by MIME type.
 *
 * Mirrors backend/routers/documents.py's `_ACCEPTED_CONTENT_TYPES`
 * check (also accepting `application/octet-stream` for the same
 * reason that module documents: some browsers/OS file-type
 * associations report PDFs under the generic binary type).
 */
export function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.type === "application/octet-stream";
}

/**
 * True if `file` is at or under MAX_PDF_UPLOAD_BYTES.
 *
 * Deliberately stricter than the backend's own limit --
 * `Settings.max_upload_size_mb` defaults to 20MB, but this task's
 * acceptance criterion specifically asks for "<10MB", so the frontend
 * enforces the tighter bound and fails fast client-side rather than
 * letting a caller upload up to 20MB only to learn about a different,
 * undocumented-to-them limit.
 */
export function isPdfWithinSizeLimit(file: File): boolean {
  return file.size <= MAX_PDF_UPLOAD_BYTES;
}
