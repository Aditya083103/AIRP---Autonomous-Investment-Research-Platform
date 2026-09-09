// frontend/src/pages/AnalysisPage.tsx
// AIRP -- Analysis Input page (T-058, B5)
//
// Replaces T-055's placeholder with the real form: a company
// autocomplete (B5: backed by GET /api/v1/companies/search, ~270
// companies, with src/data/nseTop50.ts as an offline/failure fallback
// -- see CompanyAutocomplete.tsx's own module docstring), an optional
// PDF upload (<=10MB, validated client-side --
// src/lib/validation/analysisSchemas.ts), and a "Start Analysis"
// button. Now behind ProtectedRoute (src/routes/AppRoutes.tsx) --
// starting an analysis requires an authenticated user's Bearer token,
// so the placeholder's "public page" status no longer applies once the
// form actually calls the backend.
//
// Why `selectedCompany` is its own piece of state, not re-derived from
// a static list by ticker (B5)
// ------------------------------------------------------------------------
// Before B5, this form stored only the selected ticker in
// react-hook-form state and looked the full NseCompany (name, exchange)
// back up from NSE_TOP_50 by that ticker when it needed it for the API
// calls below -- safe ONLY because NSE_TOP_50 was the exact list
// CompanyAutocomplete ever offered. Now that the autocomplete searches
// a ~270-company backend universe, most selections are NOT in
// NSE_TOP_50 at all, so that lookup would silently fail for them.
// CompanyAutocomplete's onChange already hands back the FULL selected
// company object at selection time -- this form now keeps that object
// directly (selectedCompany) instead of discarding everything but the
// ticker and trying to re-derive it later.
//
// Submit order when a PDF is attached: upload FIRST, then start the
// analysis. backend/services/documents.py's ingestion is independent of
// any specific analysis job (it links the document to a
// company/ticker, not a job_id), but starting the pipeline before the
// upload finishes risks the News Sentiment / Macro Economist agents
// querying ChromaDB for this run before the just-uploaded document is
// embedded -- a race this form avoids by simply doing the two requests
// in the order that matters, and refusing to start the analysis at all
// if the upload the user explicitly asked for fails.

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";

import { AnalysisApiError, startAnalysis, uploadDocument } from "@/api/analysis";
import { CompanyAutocomplete } from "@/components/analysis/CompanyAutocomplete";
import { HorizonSelect } from "@/components/analysis/HorizonSelect";
import { PdfUploadField } from "@/components/analysis/PdfUploadField";
import { Button } from "@/components/ui";
import { type NseCompany } from "@/data/nseTop50";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/toast";
import {
  analysisInputSchema,
  DEFAULT_ANALYSIS_HORIZON,
  isPdfFile,
  isPdfWithinSizeLimit,
  type AnalysisInputFormValues,
} from "@/lib/validation/analysisSchemas";

export function AnalysisPage(): JSX.Element {
  const { accessToken } = useAuth();
  const navigate = useNavigate();
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  // (B5) The full company CompanyAutocomplete's onChange handed back at
  // selection time -- see this file's own module docstring for why
  // this is no longer re-derived from a static list by ticker.
  const [selectedCompany, setSelectedCompany] = useState<NseCompany | null>(null);

  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AnalysisInputFormValues>({
    resolver: zodResolver(analysisInputSchema),
    defaultValues: { companyTicker: "", horizon: DEFAULT_ANALYSIS_HORIZON },
  });

  function handlePdfChange(selected: File | null): void {
    setPdfError(null);
    if (selected === null) {
      setPdfFile(null);
      return;
    }
    if (!isPdfFile(selected)) {
      setPdfError("Only PDF files are accepted.");
      setPdfFile(null);
      return;
    }
    if (!isPdfWithinSizeLimit(selected)) {
      setPdfError("PDF must be smaller than 10MB.");
      setPdfFile(null);
      return;
    }
    setPdfFile(selected);
  }

  const onSubmit = async (values: AnalysisInputFormValues): Promise<void> => {
    setFormError(null);

    if (accessToken === null) {
      setFormError("You must be logged in to start an analysis.");
      return;
    }
    // (B5) selectedCompany is set directly by CompanyAutocomplete's
    // onChange -- see this file's own module docstring. Guards
    // against a mismatch between it and the RHF-tracked ticker (e.g.
    // the field was cleared) rather than assuming they always agree.
    const company = selectedCompany;
    if (!company || company.ticker !== values.companyTicker) {
      setFormError("Select a company from the list.");
      return;
    }

    try {
      if (pdfFile !== null) {
        await uploadDocument({
          accessToken,
          file: pdfFile,
          companyName: company.name,
          ticker: company.ticker,
          exchange: company.exchange,
        });
      }

      const started = await startAnalysis({
        accessToken,
        companyName: company.name,
        ticker: company.ticker,
        exchange: company.exchange,
        period: values.horizon,
      });
      navigate(`/analysis/${started.job_id}/result`, { replace: true });
    } catch (error) {
      const message =
        error instanceof AnalysisApiError
          ? error.message
          : "Could not start the analysis. Please try again.";
      setFormError(message);
      // T-066: uploadDocument/startAnalysis are called directly here
      // rather than through a React Query mutation (see this file's
      // own module docstring on why upload has to happen before
      // start, sequentially, in one try block) -- see LoginPage.tsx's
      // identical catch block for why that means the global
      // mutation-error toast doesn't cover this call.
      toast.error(message);
    }
  };

  return (
    <div className="mx-auto max-w-lg py-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">New analysis</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        Run the committee on a company.
      </h1>
      <p className="mt-2 text-sm text-muted">
        Pick an NSE company and, optionally, attach its latest annual report -- the committee will
        read it before debating.
      </p>

      <form className="mt-8 flex flex-col gap-6" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Controller
          control={control}
          name="companyTicker"
          render={({ field }) => (
            <CompanyAutocomplete
              label="Company"
              value={selectedCompany}
              onChange={(company) => {
                setSelectedCompany(company);
                field.onChange(company ? company.ticker : "");
              }}
              accessToken={accessToken}
              hint="Search by name or ticker, e.g. 'Infosys' or 'TCS'."
              {...(errors.companyTicker?.message ? { error: errors.companyTicker.message } : {})}
            />
          )}
        />

        <HorizonSelect
          label="Analysis horizon"
          hint="How far back the Technical Analyst looks at price history."
          {...register("horizon")}
        />

        <PdfUploadField
          file={pdfFile}
          onChange={handlePdfChange}
          {...(pdfError ? { error: pdfError } : {})}
        />

        {formError ? (
          <p role="alert" className="text-sm text-verdict-sell">
            {formError}
          </p>
        ) : null}

        <Button type="submit" isLoading={isSubmitting} disabled={pdfError !== null} fullWidth>
          Start Analysis
        </Button>
      </form>
    </div>
  );
}
