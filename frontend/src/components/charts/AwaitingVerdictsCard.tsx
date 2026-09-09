// frontend/src/components/charts/AwaitingVerdictsCard.tsx
// AIRP -- Awaiting-evaluation verdicts card (B7)
//
// Lists each still-pending verdict_outcomes row (GET /api/v1/accuracy/
// history, directional_correct === null) with its scheduled scoring date
// (verdict_date + evaluation_horizon_days, computed by
// src/lib/accuracy/awaitingVerdicts.ts) -- visible proof the accuracy
// pipeline is alive even while every chart below it is still empty for a
// freshly-launched deployment. Styled like AccuracySummaryStats' KPI tiles
// (Card, mono uppercase label) rather than as a data table, since this is
// still an at-a-glance summary, not a paginated list -- MAX_VISIBLE_AWAITING
// caps the row count the same way a KPI row stays compact regardless of how
// much underlying data feeds it.

import { Badge, Card } from "@/components/ui";
import { getAwaitingVerdicts } from "@/lib/accuracy/awaitingVerdicts";
import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";
import { type Verdict } from "@/types/analysis";

export interface AwaitingVerdictsCardProps {
  entries: AccuracyHistoryEntryResponse[];
}

/** Most-imminent pending verdicts shown before collapsing the rest into a "+N more" line. */
const MAX_VISIBLE_AWAITING = 8;

const VERDICT_TONE: Record<Verdict, "buy" | "hold" | "sell"> = {
  BUY: "buy",
  HOLD: "hold",
  SELL: "sell",
};

function formatScheduledDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Renders each pending verdict's scheduled scoring date, soonest first, capped at MAX_VISIBLE_AWAITING. */
export function AwaitingVerdictsCard({ entries }: AwaitingVerdictsCardProps): JSX.Element {
  const awaiting = getAwaitingVerdicts(entries);
  const visible = awaiting.slice(0, MAX_VISIBLE_AWAITING);
  const hiddenCount = awaiting.length - visible.length;

  return (
    <Card data-testid="awaiting-verdicts-card">
      <Card.Header>
        <Card.Title>Awaiting evaluation</Card.Title>
      </Card.Header>
      {awaiting.length === 0 ? (
        <p className="text-sm text-muted">
          Nothing is currently awaiting evaluation -- every issued verdict has already been scored.
        </p>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {visible.map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-4 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge tone={VERDICT_TONE[item.verdict]}>{item.verdict}</Badge>
                  <span className="font-mono text-ink">{item.ticker}</span>
                </div>
                <span className="text-xs text-muted">
                  Scored on {formatScheduledDate(item.scheduled_scoring_date)}
                </span>
              </li>
            ))}
          </ul>
          {hiddenCount > 0 ? (
            <p className="mt-2 text-xs text-muted">
              +{hiddenCount} more {hiddenCount === 1 ? "verdict" : "verdicts"} awaiting evaluation
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}
