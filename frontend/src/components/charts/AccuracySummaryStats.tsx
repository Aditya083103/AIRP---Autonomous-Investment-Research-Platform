// frontend/src/components/charts/AccuracySummaryStats.tsx
// AIRP -- Accuracy summary stat row (T-092, B11)
//
// A 5-tile overview -- overall accuracy, total scored verdicts, total
// still pending, best verdict type, worst verdict type -- rendered above
// the three T-092 charts on AccuracyPage. Not itself one of the task's
// three named charts (rolling trend / verdict bar / conviction scatter);
// it exists because GET /api/v1/accuracy/summary's top-level fields
// (overall_accuracy_pct, total_evaluated, total_pending, by_verdict)
// would otherwise go completely unused by this page despite being the
// first, most-requested numbers a "public accuracy dashboard" visitor
// wants -- the same reasoning ChartsPanel.tsx's data_warnings banner
// sits above that page's own charts rather than being dropped for
// having no chart of its own.
//
// B11 adds the best/worst verdict-type tiles (src/lib/accuracy/
// bestWorstVerdict.ts's computeBestWorstVerdict), and B10 adds
// AnimatedNumber (each numeric value counts up on mount), Reveal
// (staggered tile entrance), and TiltCard (pointer-tracked 3D tilt) --
// the same KPI-card treatment DashboardKpiRow.tsx and CompareKpiRow.tsx
// already establish.

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { Reveal } from "@/components/motion/Reveal";
import { TiltCard } from "@/components/three/TiltCard";
import { Badge, Card } from "@/components/ui";
import { computeBestWorstVerdict } from "@/lib/accuracy/bestWorstVerdict";
import { type AccuracySummaryResponse } from "@/types/accuracy";
import { type Verdict } from "@/types/analysis";

export interface AccuracySummaryStatsProps {
  summary: AccuracySummaryResponse;
}

interface NumericTile {
  kind: "numeric";
  id: string;
  label: string;
  value: number;
  format: (value: number) => string;
}

interface VerdictTile {
  kind: "verdict";
  id: string;
  label: string;
  verdict: Verdict;
  accuracyPct: number;
}

interface PlaceholderTile {
  kind: "placeholder";
  id: string;
  label: string;
}

type StatTile = NumericTile | VerdictTile | PlaceholderTile;

const VERDICT_TONE: Record<Verdict, "buy" | "hold" | "sell"> = {
  BUY: "buy",
  HOLD: "hold",
  SELL: "sell",
};

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatCount(value: number): string {
  return Math.round(value).toLocaleString("en-IN");
}

function buildTiles(summary: AccuracySummaryResponse): StatTile[] {
  const { best, worst } = computeBestWorstVerdict(summary.by_verdict);

  return [
    summary.overall_accuracy_pct === null
      ? { kind: "placeholder", id: "overall_accuracy", label: "Overall accuracy" }
      : {
          kind: "numeric",
          id: "overall_accuracy",
          label: "Overall accuracy",
          value: summary.overall_accuracy_pct,
          format: formatPercent,
        },
    {
      kind: "numeric",
      id: "verdicts_scored",
      label: "Verdicts scored",
      value: summary.total_evaluated,
      format: formatCount,
    },
    {
      kind: "numeric",
      id: "awaiting_evaluation",
      label: "Awaiting evaluation",
      value: summary.total_pending,
      format: formatCount,
    },
    best === null
      ? { kind: "placeholder", id: "best_verdict", label: "Best verdict type" }
      : {
          kind: "verdict",
          id: "best_verdict",
          label: "Best verdict type",
          verdict: best.verdict,
          accuracyPct: best.accuracy_pct,
        },
    worst === null
      ? { kind: "placeholder", id: "worst_verdict", label: "Worst verdict type" }
      : {
          kind: "verdict",
          id: "worst_verdict",
          label: "Worst verdict type",
          verdict: worst.verdict,
          accuracyPct: worst.accuracy_pct,
        },
  ];
}

function TileValue({ tile }: { tile: StatTile }): JSX.Element {
  if (tile.kind === "placeholder") {
    return <p className="mt-2 font-display text-3xl font-semibold text-ink">--</p>;
  }
  if (tile.kind === "numeric") {
    return (
      <p className="mt-2 font-display text-3xl font-semibold text-ink">
        <AnimatedNumber value={tile.value} format={tile.format} />
      </p>
    );
  }
  return (
    <div className="mt-2 flex items-center gap-2">
      <Badge tone={VERDICT_TONE[tile.verdict]}>{tile.verdict}</Badge>
      <span className="font-mono text-lg font-semibold text-ink">
        <AnimatedNumber value={tile.accuracyPct} format={formatPercent} />
      </span>
    </div>
  );
}

/** Renders the Accuracy dashboard's 5-tile KPI row: accuracy, scored, awaiting, best/worst verdict. */
export function AccuracySummaryStats({ summary }: AccuracySummaryStatsProps): JSX.Element {
  const tiles = buildTiles(summary);

  return (
    <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="accuracy-summary-stats">
      {tiles.map((tile, index) => (
        <Reveal key={tile.id} index={index}>
          <TiltCard>
            <Card>
              <p className="font-mono text-xs uppercase tracking-[0.15em] text-muted">
                {tile.label}
              </p>
              <TileValue tile={tile} />
            </Card>
          </TiltCard>
        </Reveal>
      ))}
    </div>
  );
}
