// frontend/src/components/results/ResultsPanel.tsx
// AIRP -- Analysis Results panel (T-061)
//
// The T-061 deliverable: composes every InvestmentDecisionResponse
// field into one scrollable results view -- verdict + conviction
// gauge first (the single most important fact), then the Investment
// Memo's prose sections, bull/bear case, structured risks/catalysts,
// valuation, the Portfolio Manager's resolution of the Contrarian's
// strongest argument, and finally how much weight each agent's output
// received. Rendered by AnalysisResultPage once the live event stream
// reports the pipeline finished successfully (see that page's
// docstring for why the fetch is gated on `is_final && !hasFailed`
// rather than firing eagerly).
//
// Layout is a single vertical `space-y` stack -- every child panel
// (VerdictPanel, BullBearPanel, KeyRisksList) already handles its own
// internal responsive grid, so this component does not need any
// breakpoint logic of its own for "responsive layout" to hold.

import { AgentWeightsPanel } from "@/components/results/AgentWeightsPanel";
import { BullBearPanel } from "@/components/results/BullBearPanel";
import { KeyRisksList } from "@/components/results/KeyRisksList";
import { MemoSection } from "@/components/results/MemoSection";
import { VerdictPanel } from "@/components/results/VerdictPanel";
import { type InvestmentDecisionResponse } from "@/types/analysis";

export interface ResultsPanelProps {
  decision: InvestmentDecisionResponse;
}

function formatGeneratedAt(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) {
    return isoTimestamp;
  }
  return parsed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

/** Renders the complete Investment Memo -- every InvestmentDecisionResponse field. */
export function ResultsPanel({ decision }: ResultsPanelProps): JSX.Element {
  return (
    <div className="space-y-6" data-testid="results-panel">
      <VerdictPanel decision={decision} />

      <MemoSection title="Executive summary" content={decision.executive_summary} />
      <MemoSection title="Investment thesis" content={decision.investment_thesis} />

      <BullBearPanel bullCase={decision.bull_case} bearCase={decision.bear_case} />

      <KeyRisksList
        riskSummary={decision.risk_summary}
        keyRisks={decision.key_risks}
        keyCatalysts={decision.key_catalysts}
      />

      <MemoSection title="Valuation" content={decision.valuation_summary} />

      <MemoSection
        title={`Contrarian resolution (${decision.debate_rounds_used} debate round${
          decision.debate_rounds_used === 1 ? "" : "s"
        })`}
        content={decision.contrarian_response}
        emptyLabel="The Portfolio Manager did not record a direct response to the Contrarian Investor."
      />

      <AgentWeightsPanel agentWeights={decision.agent_weights} />

      <p className="text-center font-mono text-xs text-muted" data-testid="results-panel-meta">
        {decision.company_name} ({decision.ticker}) -- Investment Memo generated{" "}
        {formatGeneratedAt(decision.generated_at)}
      </p>
    </div>
  );
}
