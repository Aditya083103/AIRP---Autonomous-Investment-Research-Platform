// frontend/src/pages/MemoPage.tsx
// AIRP -- Investment Memo page (T-063)
//
// A dedicated, print-friendly-by-design view of one completed
// analysis's Investment Memo: the same InvestmentDecisionResponse
// AnalysisResultPage.tsx (T-061) already fetches via useAnalysisResult,
// but rendered here as its own full-width page with every prose/
// structured section wrapped in a <CollapsibleSection> so a reader can
// collapse the sections they don't need and scan the memo's shape at a
// glance, plus a <MemoToolbar> for downloading the branded PDF (GET
// /api/v1/analysis/{job_id}/memo/pdf) and copying a shareable link.
//
// Deliberately a separate route from /analysis/:jobId/result rather
// than folding this layout into ResultsPanel.tsx in place: the result
// page's job is live progress + a first look at the verdict the
// moment the pipeline finishes, while this page's job is the polished,
// revisitable memo a person opens later, links to a colleague, or
// downloads as a PDF -- two different reading contexts for the same
// underlying data, not two implementations of the same page. Linked to
// from AnalysisResultPage once an analysis completes successfully.
//
// The verdict itself (VerdictPanel) is intentionally NOT wrapped in a
// CollapsibleSection -- it is the one section a reader should never
// have to expand to see the headline BUY/HOLD/SELL call.

import { useParams } from "react-router-dom";

import { MemoToolbar } from "@/components/memo";
import { AgentWeightsPanel, BullBearPanel, KeyRisksList, VerdictPanel } from "@/components/results";
import { CollapsibleSection, Spinner } from "@/components/ui";
import { useAnalysisResult } from "@/hooks/useAnalysisResult";
import { useAuth } from "@/hooks/useAuth";

function formatGeneratedAt(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return isoTimestamp;
  }
  return parsed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function MemoPage(): JSX.Element {
  const { jobId } = useParams<{ jobId: string }>();
  const { accessToken } = useAuth();

  const {
    data: decision,
    isPending,
    isError,
    error,
  } = useAnalysisResult({
    jobId: jobId ?? "",
    accessToken,
    enabled: jobId !== undefined && accessToken !== null,
  });

  if (jobId === undefined) {
    return (
      <div className="mx-auto max-w-lg py-16 text-center">
        <p className="text-sm text-muted">No analysis job specified.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl py-12" data-testid="memo-page">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Investment memo</p>
      <h1 className="mt-2 font-display text-3xl font-semibold text-ink">
        {decision ? `${decision.company_name} (${decision.ticker})` : "Investment memo"}
      </h1>
      {decision ? (
        <p className="mt-2 font-mono text-xs text-muted">
          Generated {formatGeneratedAt(decision.generated_at)}
        </p>
      ) : (
        <p className="mt-2 font-mono text-xs text-muted">Job ID: {jobId}</p>
      )}

      {accessToken !== null ? (
        <div className="mt-6">
          <MemoToolbar accessToken={accessToken} jobId={jobId} />
        </div>
      ) : null}

      {isPending ? (
        <div className="mt-10 flex items-center gap-2 text-sm text-muted">
          <Spinner size="sm" aria-hidden="true" />
          Loading the Investment Memo…
        </div>
      ) : null}

      {isError ? (
        <p className="mt-10 text-sm text-verdict-sell" role="alert">
          {error instanceof Error
            ? error.message
            : "Could not load the Investment Memo. Please try refreshing the page."}
        </p>
      ) : null}

      {decision ? (
        <div className="mt-8 space-y-4">
          <VerdictPanel decision={decision} />

          <CollapsibleSection title="Executive summary">
            <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
              {decision.executive_summary || "Not available for this analysis."}
            </p>
          </CollapsibleSection>

          <CollapsibleSection title="Investment thesis">
            <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
              {decision.investment_thesis || "Not available for this analysis."}
            </p>
          </CollapsibleSection>

          <CollapsibleSection title="Bull case & bear case">
            <BullBearPanel bullCase={decision.bull_case} bearCase={decision.bear_case} />
          </CollapsibleSection>

          <CollapsibleSection title="Key risks & catalysts">
            <KeyRisksList
              riskSummary={decision.risk_summary}
              keyRisks={decision.key_risks}
              keyCatalysts={decision.key_catalysts}
            />
          </CollapsibleSection>

          <CollapsibleSection title="Valuation">
            <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
              {decision.valuation_summary || "Not available for this analysis."}
            </p>
          </CollapsibleSection>

          <CollapsibleSection
            title={`Contrarian resolution (${decision.debate_rounds_used} debate round${
              decision.debate_rounds_used === 1 ? "" : "s"
            })`}
          >
            <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
              {decision.contrarian_response ||
                "The Portfolio Manager did not record a direct response to the " +
                  "Contrarian Investor."}
            </p>
          </CollapsibleSection>

          <CollapsibleSection title="Agent weighting" defaultOpen={false}>
            <AgentWeightsPanel agentWeights={decision.agent_weights} />
          </CollapsibleSection>
        </div>
      ) : null}
    </div>
  );
}
