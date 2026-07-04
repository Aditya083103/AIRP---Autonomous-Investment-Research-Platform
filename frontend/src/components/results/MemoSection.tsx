// frontend/src/components/results/MemoSection.tsx
// AIRP -- Generic Investment Memo prose section (T-061)
//
// A single reusable "title + paragraph" card, used for every free-text
// InvestmentDecisionResponse field that doesn't need its own bespoke
// layout (executive_summary, investment_thesis, valuation_summary,
// contrarian_response) -- rather than four near-identical bespoke
// components, one parameterised card keeps ResultsPanel.tsx's
// composition readable and keeps this styling in exactly one place.

import { Card } from "@/components/ui";

export interface MemoSectionProps {
  title: string;
  content: string;
  /** Shown instead of `content` when it is an empty string. */
  emptyLabel?: string;
}

/** A titled card rendering one Investment Memo prose section. */
export function MemoSection({
  title,
  content,
  emptyLabel = "Not available for this analysis.",
}: MemoSectionProps): JSX.Element {
  return (
    <Card>
      <Card.Header>
        <Card.Title>{title}</Card.Title>
      </Card.Header>
      <p className="whitespace-pre-line text-sm leading-relaxed text-ink">
        {content || emptyLabel}
      </p>
    </Card>
  );
}
