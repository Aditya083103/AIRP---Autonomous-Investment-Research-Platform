// frontend/src/pages/AnalysisPage.tsx
// AIRP -- Analysis Input page (T-058)
//
// Replaces T-055's placeholder with the real form: a company
// autocomplete over the static top-50 NSE list (src/data/nseTop50.ts),
// an optional PDF upload (<=10MB, validated client-side --
// src/lib/validation/analysisSchemas.ts), and a "Start Analysis"
// button. Now behind ProtectedRoute (src/routes/AppRoutes.tsx) --
// starting an analysis requires an authenticated user's Bearer token,
// so the placeholder's "public page" status no longer applies once the
// form actually calls the backend.
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
import { NSE_TOP_50 } from "@/data/nseTop50";
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
    const company = NSE_TOP_50.find((candidate) => candidate.ticker === values.companyTicker);
    if (!company) {
      // Unreachable in practice: zod already required a non-empty
      // companyTicker, and CompanyAutocomplete only ever writes a
      // ticker that came from this exact list. Guards against the
      // lookup silently returning undefined rather than asserting.
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
          render={({ field }) => {
            const selected = NSE_TOP_50.find((company) => company.ticker === field.value) ?? null;
            return (
              <CompanyAutocomplete
                label="Company"
                value={selected}
                onChange={(company) => field.onChange(company ? company.ticker : "")}
                options={NSE_TOP_50}
                hint="Search by name or ticker, e.g. 'Infosys' or 'TCS'."
                {...(errors.companyTicker?.message ? { error: errors.companyTicker.message } : {})}
              />
            );
          }}
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
