// frontend/src/lib/validation/compareSchemas.ts
// AIRP -- Compare input form schema (T-064)
//
// Same `companyTicker: string` shape src/lib/validation/analysisSchemas.ts
// already uses for the single-company form, doubled into companyTickerA
// / companyTickerB -- and for the same reason documented there: a plain
// string field (empty = nothing selected) avoids the react-hook-form
// `DeepPartial` typing trouble a nullable NseCompany object field hits.
//
// The one rule this schema adds beyond "both selected" is `.refine`-ing
// that the two tickers differ -- comparing a company against itself
// would still "work" (two identical analyses run in parallel) but is
// never useful, so this catches it before either request is even sent
// rather than surfacing an unhelpful side-by-side of identical numbers.

import { z } from "zod";

export const compareInputSchema = z
  .object({
    companyTickerA: z.string().min(1, "Select the first company."),
    companyTickerB: z.string().min(1, "Select the second company."),
  })
  .refine((values) => values.companyTickerA !== values.companyTickerB, {
    message: "Choose two different companies to compare.",
    path: ["companyTickerB"],
  });

export type CompareInputFormValues = z.infer<typeof compareInputSchema>;
