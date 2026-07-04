// frontend/src/components/results/KeyRisksList.tsx
// AIRP -- Key risks & catalysts panel (T-061)
//
// Renders InvestmentDecisionResponse.risk_summary alongside the two
// structured lists the Portfolio Manager produces: key_risks (capped
// at 6, critical Risk Officer flags first) and key_catalysts (capped
// at 5). Two columns on desktop, stacked on mobile -- the same
// responsive grid pattern as BullBearPanel, since risks and catalysts
// are naturally a "what could go wrong" / "what could go right" pair
// the way bull/bear case is.

import { Card } from "@/components/ui";

export interface KeyRisksListProps {
  riskSummary: string;
  keyRisks: string[];
  keyCatalysts: string[];
}

/** Renders the risk summary plus the structured key-risks and key-catalysts lists. */
export function KeyRisksList({
  riskSummary,
  keyRisks,
  keyCatalysts,
}: KeyRisksListProps): JSX.Element {
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="key-risks-list">
      <Card>
        <Card.Header>
          <Card.Title>Key risks</Card.Title>
        </Card.Header>
        {riskSummary ? <p className="text-sm leading-relaxed text-muted">{riskSummary}</p> : null}
        {keyRisks.length > 0 ? (
          <ul className="mt-3 space-y-2">
            {keyRisks.map((risk) => (
              <li key={risk} className="flex gap-2 text-sm text-ink">
                <span aria-hidden="true" className="mt-0.5 text-verdict-sell">
                  &#9650;
                </span>
                <span>{risk}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted">No structured risks were flagged.</p>
        )}
      </Card>

      <Card>
        <Card.Header>
          <Card.Title>Key catalysts</Card.Title>
        </Card.Header>
        {keyCatalysts.length > 0 ? (
          <ul className="space-y-2">
            {keyCatalysts.map((catalyst) => (
              <li key={catalyst} className="flex gap-2 text-sm text-ink">
                <span aria-hidden="true" className="mt-0.5 text-verdict-buy">
                  &#9679;
                </span>
                <span>{catalyst}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No catalysts were identified.</p>
        )}
      </Card>
    </div>
  );
}
