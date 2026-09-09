// frontend/src/components/compare/CompareInputForm.tsx
// AIRP -- Compare input form (T-064, B5)
//
// Two CompanyAutocomplete instances (reused as-is from T-058, no
// compare-specific fork) plus a single submit button. Deliberately
// does not accept a PDF upload the way AnalysisPage.tsx does -- there
// is no way to attribute one uploaded document to "company A" vs
// "company B" without a second upload control, and the compare flow's
// acceptance criteria (T-064) never asked for document-enriched
// comparisons, so that scope is left out rather than half-built.
//
// Validation lives in src/lib/validation/compareSchemas.ts -- both
// fields required, and the same ticker cannot be selected twice.
//
// Why selectedCompanyA/B are their own state, not re-derived from
// NSE_TOP_50 by ticker (B5) -- see AnalysisPage.tsx's identical note:
// CompanyAutocomplete now searches a ~270-company backend universe
// (GET /api/v1/companies/search), so most selections are not in the
// 51-entry NSE_TOP_50 fallback list a by-ticker lookup would need.

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { CompanyAutocomplete } from "@/components/analysis/CompanyAutocomplete";
import { Button } from "@/components/ui";
import { type NseCompany } from "@/data/nseTop50";
import { compareInputSchema, type CompareInputFormValues } from "@/lib/validation/compareSchemas";

export interface CompareInputFormProps {
  onSubmit: (companyA: NseCompany, companyB: NseCompany) => void;
  isSubmitting: boolean;
  /** Bearer token, forwarded to both CompanyAutocomplete instances -- see that component's own module docstring. */
  accessToken: string | null;
  formError?: string;
}

/** The two-company picker that kicks off a side-by-side comparison run. */
export function CompareInputForm({
  onSubmit,
  isSubmitting,
  accessToken,
  formError,
}: CompareInputFormProps): JSX.Element {
  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<CompareInputFormValues>({
    resolver: zodResolver(compareInputSchema),
    defaultValues: { companyTickerA: "", companyTickerB: "" },
  });
  const [selectedCompanyA, setSelectedCompanyA] = useState<NseCompany | null>(null);
  const [selectedCompanyB, setSelectedCompanyB] = useState<NseCompany | null>(null);

  function submit(values: CompareInputFormValues): void {
    if (
      !selectedCompanyA ||
      !selectedCompanyB ||
      selectedCompanyA.ticker !== values.companyTickerA ||
      selectedCompanyB.ticker !== values.companyTickerB
    ) {
      return;
    }
    onSubmit(selectedCompanyA, selectedCompanyB);
  }

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(event) => void handleSubmit(submit)(event)}
      noValidate
      data-testid="compare-input-form"
    >
      <div className="grid gap-6 sm:grid-cols-2">
        <Controller
          control={control}
          name="companyTickerA"
          render={({ field }) => (
            <CompanyAutocomplete
              label="Company A"
              value={selectedCompanyA}
              onChange={(company) => {
                setSelectedCompanyA(company);
                field.onChange(company ? company.ticker : "");
              }}
              accessToken={accessToken}
              hint="e.g. 'TCS'"
              {...(errors.companyTickerA?.message ? { error: errors.companyTickerA.message } : {})}
            />
          )}
        />

        <Controller
          control={control}
          name="companyTickerB"
          render={({ field }) => (
            <CompanyAutocomplete
              label="Company B"
              value={selectedCompanyB}
              onChange={(company) => {
                setSelectedCompanyB(company);
                field.onChange(company ? company.ticker : "");
              }}
              accessToken={accessToken}
              hint="e.g. 'Infosys'"
              {...(errors.companyTickerB?.message ? { error: errors.companyTickerB.message } : {})}
            />
          )}
        />
      </div>

      {formError ? (
        <p role="alert" className="text-sm text-verdict-sell">
          {formError}
        </p>
      ) : null}

      <Button type="submit" isLoading={isSubmitting} fullWidth>
        Compare Companies
      </Button>
    </form>
  );
}
