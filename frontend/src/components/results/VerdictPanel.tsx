// frontend/src/components/results/VerdictPanel.tsx
// AIRP -- Verdict panel (T-061)
//
// The top-of-page summary of an InvestmentDecisionResponse: the
// BUY/HOLD/SELL badge, the animated conviction gauge, the one-sentence
// dashboard summary, and the price target / time horizon pair. This is
// the single most important panel on the results page -- it is
// designed to be legible on its own even if the person never scrolls
// to the bull/bear case or memo sections below.

import { ConvictionGauge } from "@/components/results/ConvictionGauge";
import { Badge, Card, type BadgeTone } from "@/components/ui";
import { type InvestmentDecisionResponse, type Verdict } from "@/types/analysis";

export interface VerdictPanelProps {
  decision: InvestmentDecisionResponse;
}

const VERDICT_TONE: Record<Verdict, BadgeTone> = {
  BUY: "buy",
  HOLD: "hold",
  SELL: "sell",
};

/** Renders the Portfolio Manager's final verdict, conviction gauge, price target, and time horizon. */
export function VerdictPanel({ decision }: VerdictPanelProps): JSX.Element {
  return (
    <Card data-testid="verdict-panel">
      <div className="grid gap-6 sm:grid-cols-[220px,1fr] sm:items-center">
        <ConvictionGauge score={decision.conviction_score} verdict={decision.verdict} />

        <div>
          <Badge tone={VERDICT_TONE[decision.verdict]} className="px-3 py-1 text-sm">
            {decision.verdict}
          </Badge>

          {decision.summary ? (
            <p className="mt-3 text-sm leading-relaxed text-ink">{decision.summary}</p>
          ) : null}

          <dl className="mt-4 grid grid-cols-2 gap-4">
            <div>
              <dt className="font-mono text-xs uppercase tracking-wide text-muted">Price target</dt>
              <dd className="mt-1 font-mono text-sm text-ink">
                {decision.price_target ?? "Not determined"}
              </dd>
            </div>
            <div>
              <dt className="font-mono text-xs uppercase tracking-wide text-muted">Time horizon</dt>
              <dd className="mt-1 font-mono text-sm text-ink">{decision.time_horizon}</dd>
            </div>
          </dl>
        </div>
      </div>
    </Card>
  );
}
