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
//
// B10: every section below VerdictPanel (which animates itself, see
// its own docstring) fades/rises in via a staggered Reveal, so the
// whole memo cascades into view top-to-bottom rather than appearing as
// one static block the instant the fetch resolves.

import { Reveal } from "@/components/motion/Reveal";
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

      <Reveal index={1}>
        <MemoSection title="Executive summary" content={decision.executive_summary} />
      </Reveal>
      <Reveal index={2}>
        <MemoSection title="Investment thesis" content={decision.investment_thesis} />
      </Reveal>

      <Reveal index={3}>
        <BullBearPanel bullCase={decision.bull_case} bearCase={decision.bear_case} />
      </Reveal>

      <Reveal index={4}>
        <KeyRisksList
          riskSummary={decision.risk_summary}
          keyRisks={decision.key_risks}
          keyCatalysts={decision.key_catalysts}
        />
      </Reveal>

      <Reveal index={5}>
        <MemoSection title="Valuation" content={decision.valuation_summary} />
      </Reveal>

      <Reveal index={6}>
        <MemoSection
          title={`Contrarian resolution (${decision.debate_rounds_used} debate round${
            decision.debate_rounds_used === 1 ? "" : "s"
          })`}
          content={decision.contrarian_response}
          emptyLabel="The Portfolio Manager did not record a direct response to the Contrarian Investor."
        />
      </Reveal>

      <Reveal index={7}>
        <AgentWeightsPanel agentWeights={decision.agent_weights} />
      </Reveal>

      <p className="text-center font-mono text-xs text-muted" data-testid="results-panel-meta">
        {decision.company_name} ({decision.ticker}) -- Investment Memo generated{" "}
        {formatGeneratedAt(decision.generated_at)}
      </p>
    </div>
  );
}
