// frontend/src/components/charts/AccuracySummaryStats.tsx
// AIRP -- Accuracy summary stat row (T-092)
//
// A compact three-tile overview -- overall accuracy, total scored
// verdicts, total still pending -- rendered above the three T-092
// charts on AccuracyPage. Not itself one of the task's three named
// charts (rolling trend / verdict bar / conviction scatter); it exists
// because GET /api/v1/accuracy/summary's top-level fields
// (overall_accuracy_pct, total_evaluated, total_pending) would
// otherwise go completely unused by this page despite being the first,
// most-requested numbers a "public accuracy dashboard" visitor wants --
// the same reasoning ChartsPanel.tsx's data_warnings banner sits above
// that page's own charts rather than being dropped for having no chart
// of its own.

import { Card } from "@/components/ui";
import { type AccuracySummaryResponse } from "@/types/accuracy";

export interface AccuracySummaryStatsProps {
  summary: AccuracySummaryResponse;
}

interface StatTile {
  label: string;
  value: string;
}

function formatPercent(value: number | null): string {
  return value === null ? "--" : `${value.toFixed(1)}%`;
}

function buildTiles(summary: AccuracySummaryResponse): StatTile[] {
  return [
    { label: "Overall accuracy", value: formatPercent(summary.overall_accuracy_pct) },
    { label: "Verdicts scored", value: summary.total_evaluated.toLocaleString("en-IN") },
    { label: "Awaiting evaluation", value: summary.total_pending.toLocaleString("en-IN") },
  ];
}

/** Renders a 3-tile overview row: overall accuracy, verdicts scored, verdicts still pending. */
export function AccuracySummaryStats({ summary }: AccuracySummaryStatsProps): JSX.Element {
  const tiles = buildTiles(summary);

  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="accuracy-summary-stats">
      {tiles.map((tile) => (
        <Card key={tile.label}>
          <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">{tile.label}</p>
          <p className="mt-2 font-display text-3xl font-semibold text-ink">{tile.value}</p>
        </Card>
      ))}
    </div>
  );
}
