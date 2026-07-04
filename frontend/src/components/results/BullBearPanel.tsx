// frontend/src/components/results/BullBearPanel.tsx
// AIRP -- Bull case vs bear case panel (T-061)
//
// Side-by-side comparison of InvestmentDecisionResponse.bull_case and
// .bear_case -- the synthesised argument for the thesis (fundamental,
// technical, sentiment, macro) next to the synthesised argument
// against it (Contrarian Investor challenges + Risk Officer flags).
// "Side by side" only holds at desktop width -- on narrow viewports
// the two cards stack vertically via a single responsive grid, the
// same `grid md:grid-cols-2` pattern CommitteeSection.tsx already uses
// for its 8-seat layout, rather than a fixed-width flex row that would
// overflow on mobile.

import { Card } from "@/components/ui";

export interface BullBearPanelProps {
  bullCase: string;
  bearCase: string;
}

/** Renders the bull case and bear case as two cards, side by side on desktop. */
export function BullBearPanel({ bullCase, bearCase }: BullBearPanelProps): JSX.Element {
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="bull-bear-panel">
      <Card className="border-verdict-buy/30">
        <Card.Header>
          <Card.Title>Bull case</Card.Title>
        </Card.Header>
        <p className="text-sm leading-relaxed text-ink">
          {bullCase || "No bull case was recorded for this analysis."}
        </p>
      </Card>

      <Card className="border-verdict-sell/30">
        <Card.Header>
          <Card.Title>Bear case</Card.Title>
        </Card.Header>
        <p className="text-sm leading-relaxed text-ink">
          {bearCase || "No bear case was recorded for this analysis."}
        </p>
      </Card>
    </div>
  );
}
