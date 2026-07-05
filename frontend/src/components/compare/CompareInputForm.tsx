// frontend/src/components/compare/CompareInputForm.tsx
// AIRP -- Compare input form (T-064)
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

import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";

import { CompanyAutocomplete } from "@/components/analysis/CompanyAutocomplete";
import { Button } from "@/components/ui";
import { NSE_TOP_50, type NseCompany } from "@/data/nseTop50";
import { compareInputSchema, type CompareInputFormValues } from "@/lib/validation/compareSchemas";

export interface CompareInputFormProps {
  onSubmit: (companyA: NseCompany, companyB: NseCompany) => void;
  isSubmitting: boolean;
  formError?: string;
}

/** The two-company picker that kicks off a side-by-side comparison run. */
export function CompareInputForm({
  onSubmit,
  isSubmitting,
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

  function submit(values: CompareInputFormValues): void {
    const companyA = NSE_TOP_50.find((candidate) => candidate.ticker === values.companyTickerA);
    const companyB = NSE_TOP_50.find((candidate) => candidate.ticker === values.companyTickerB);
    if (!companyA || !companyB) {
      // Unreachable in practice -- see AnalysisPage.tsx's identical guard
      // for why: zod already required both tickers, and
      // CompanyAutocomplete only ever writes a ticker from this list.
      return;
    }
    onSubmit(companyA, companyB);
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
          render={({ field }) => {
            const selected = NSE_TOP_50.find((company) => company.ticker === field.value) ?? null;
            return (
              <CompanyAutocomplete
                label="Company A"
                value={selected}
                onChange={(company) => field.onChange(company ? company.ticker : "")}
                options={NSE_TOP_50}
                hint="e.g. 'TCS'"
                {...(errors.companyTickerA?.message
                  ? { error: errors.companyTickerA.message }
                  : {})}
              />
            );
          }}
        />

        <Controller
          control={control}
          name="companyTickerB"
          render={({ field }) => {
            const selected = NSE_TOP_50.find((company) => company.ticker === field.value) ?? null;
            return (
              <CompanyAutocomplete
                label="Company B"
                value={selected}
                onChange={(company) => field.onChange(company ? company.ticker : "")}
                options={NSE_TOP_50}
                hint="e.g. 'Infosys'"
                {...(errors.companyTickerB?.message
                  ? { error: errors.companyTickerB.message }
                  : {})}
              />
            );
          }}
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
