// frontend/src/pages/ComparePage.tsx
// AIRP -- Company Compare page (T-064)
//
// Lets a user pick two NSE companies, runs both through the full
// analysis pipeline in parallel (two independent POST /analysis/start
// calls, kicked off together via Promise.all rather than sequentially),
// then renders every metric from both completed analyses side by side
// with the better value highlighted per row -- see
// src/lib/compare/winnerLogic.ts for the winner rules and
// src/components/compare/CompanyAnalysisPanel.tsx for how each side's
// own stream/result/charts fetches stay fully independent of the
// other's.
//
// Three-stage state machine, deliberately kept as a single `stage`
// field rather than several booleans that could disagree with each
// other:
//   "form"    -- picking two companies (CompareInputForm)
//   "running" -- both jobs started; two CompanyAnalysisPanel instances
//                stream progress until each settles
//   "done"    -- both panels have settled (successfully or not); shows
//                the ComparisonTable if both succeeded, or an error
//                message naming which side(s) failed otherwise
//
// Deliberately does not let a user re-run with the results still on
// screen -- "Compare again" resets straight back to "form" rather than
// offering an in-place re-run, since two fresh job_ids are needed
// either way and there is no partial state worth preserving across a
// full re-run.

import { useEffect, useState } from "react";

import { AnalysisApiError, startAnalysis } from "@/api/analysis";
import {
  CompanyAnalysisPanel,
  type CompanyAnalysisPanelResult,
  CompareInputForm,
  ComparisonTable,
} from "@/components/compare";
import { Button } from "@/components/ui";
import { type NseCompany } from "@/data/nseTop50";
import { useAuth } from "@/hooks/useAuth";
import { buildComparisonRows } from "@/lib/compare/winnerLogic";

type CompareStage = "form" | "running" | "done";

interface CompareSide {
  company: NseCompany;
  jobId: string;
  /** `undefined` while still running, `null` if it settled without success, otherwise the result. */
  result: CompanyAnalysisPanelResult | null | undefined;
}

export function ComparePage(): JSX.Element {
  const { accessToken } = useAuth();

  const [stage, setStage] = useState<CompareStage>("form");
  const [sideA, setSideA] = useState<CompareSide | null>(null);
  const [sideB, setSideB] = useState<CompareSide | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [formError, setFormError] = useState<string | undefined>(undefined);

  function resetToForm(): void {
    setStage("form");
    setSideA(null);
    setSideB(null);
    setFormError(undefined);
  }

  async function handleSubmit(companyA: NseCompany, companyB: NseCompany): Promise<void> {
    if (accessToken === null) {
      setFormError("You must be logged in to run a comparison.");
      return;
    }
    setFormError(undefined);
    setIsStarting(true);
    try {
      const [startedA, startedB] = await Promise.all([
        startAnalysis({
          accessToken,
          companyName: companyA.name,
          ticker: companyA.ticker,
          exchange: companyA.exchange,
        }),
        startAnalysis({
          accessToken,
          companyName: companyB.name,
          ticker: companyB.ticker,
          exchange: companyB.exchange,
        }),
      ]);
      setSideA({ company: companyA, jobId: startedA.job_id, result: undefined });
      setSideB({ company: companyB, jobId: startedB.job_id, result: undefined });
      setStage("running");
    } catch (error) {
      setFormError(
        error instanceof AnalysisApiError
          ? error.message
          : "Could not start the comparison. Please try again.",
      );
    } finally {
      setIsStarting(false);
    }
  }

  function handleSettledA(result: CompanyAnalysisPanelResult | null): void {
    setSideA((current) => (current ? { ...current, result } : current));
  }

  function handleSettledB(result: CompanyAnalysisPanelResult | null): void {
    setSideB((current) => (current ? { ...current, result } : current));
  }

  const bothSettled =
    stage === "running" && sideA?.result !== undefined && sideB?.result !== undefined;

  useEffect(() => {
    if (bothSettled) {
      setStage("done");
    }
  }, [bothSettled]);

  return (
    <div className="mx-auto max-w-4xl py-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Company compare</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        Put two companies in front of the committee.
      </h1>
      <p className="mt-2 text-sm text-muted">
        Both analyses run at the same time -- every metric is compared once they finish, with the
        better value highlighted.
      </p>

      {stage === "form" ? (
        <div className="mt-8">
          <CompareInputForm
            onSubmit={(companyA, companyB) => void handleSubmit(companyA, companyB)}
            isSubmitting={isStarting}
            {...(formError ? { formError } : {})}
          />
        </div>
      ) : null}

      {(stage === "running" || stage === "done") && sideA && sideB && accessToken ? (
        <div className="mt-8 grid gap-6 sm:grid-cols-2" data-testid="compare-panels">
          <CompanyAnalysisPanel
            title={sideA.company.name}
            jobId={sideA.jobId}
            accessToken={accessToken}
            onSettled={handleSettledA}
          />
          <CompanyAnalysisPanel
            title={sideB.company.name}
            jobId={sideB.jobId}
            accessToken={accessToken}
            onSettled={handleSettledB}
          />
        </div>
      ) : null}

      {stage === "done" && sideA && sideB ? (
        <div className="mt-10">
          {sideA.result && sideB.result ? (
            <ComparisonTable
              companyNameA={sideA.company.name}
              companyNameB={sideB.company.name}
              rows={buildComparisonRows(sideA.result, sideB.result)}
            />
          ) : (
            <p className="text-sm text-verdict-sell" role="alert">
              {!sideA.result && !sideB.result
                ? "Both analyses failed to complete. Please try again."
                : `${!sideA.result ? sideA.company.name : sideB.company.name} did not complete -- ` +
                  "try comparing again."}
            </p>
          )}

          <div className="mt-6">
            <Button type="button" variant="secondary" onClick={resetToForm}>
              Compare again
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
