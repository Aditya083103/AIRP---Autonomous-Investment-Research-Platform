// frontend/src/components/charts/ConvictionAccuracyScatterChart.tsx
// AIRP -- Conviction-vs-accuracy scatter chart (T-092)
//
// One point per EVALUATED verdict_outcomes row (GET /api/v1/accuracy/
// history, T-091): x = conviction_score (1-10, the Portfolio Manager's
// own confidence at verdict time), y = price_change_pct (the actual
// market move from price_at_verdict to price_at_evaluation), coloured
// by directional_correct. This is deliberately per-analysis, not a
// bucketed rollup -- backend.services.accuracy_tracker's own module
// docstring (T-091) calls this out explicitly: "T-092's
// conviction-vs-accuracy scatter plot (which wants one point per
// analysis, not a bucketed rollup) reads from GET /accuracy/history
// instead, where conviction_score is returned unbucketed per row." The
// bucketed low/medium/high rollup (AccuracySummaryResponse.by_conviction)
// already has its own home -- the summary stats row on AccuracyPanel --
// so this chart's job is the finer-grained picture that rollup can't
// show: does a HIGH-conviction call that goes wrong still tend to be a
// smaller miss than a low-conviction one, and similar questions a
// bucketed average erases.
//
// Two Scatter series (Correct / Incorrect) rather than one series with
// per-point colouring -- Recharts colours an entire <Scatter> by its
// `fill` prop, not per-point, so two series is the straightforward way
// to get a legend that reads "green dots were right, red dots were
// wrong" instead of a single homogeneous cloud.

import {
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";

export interface ConvictionAccuracyScatterChartProps {
  entries: AccuracyHistoryEntryResponse[];
}

interface ScatterPoint {
  conviction_score: number;
  price_change_pct: number;
  verdict: string;
  ticker: string;
}

/** Only entries that have actually been scored carry both an outcome and a correctness flag. */
function toEvaluatedPoints(entries: AccuracyHistoryEntryResponse[]): {
  correct: ScatterPoint[];
  incorrect: ScatterPoint[];
} {
  const correct: ScatterPoint[] = [];
  const incorrect: ScatterPoint[] = [];

  for (const entry of entries) {
    if (entry.directional_correct === null || entry.price_change_pct === null) {
      continue;
    }
    const point: ScatterPoint = {
      conviction_score: entry.conviction_score,
      price_change_pct: entry.price_change_pct,
      verdict: entry.verdict,
      ticker: entry.ticker,
    };
    if (entry.directional_correct) {
      correct.push(point);
    } else {
      incorrect.push(point);
    }
  }

  return { correct, incorrect };
}

interface ScatterTooltipPayloadEntry {
  payload?: ScatterPoint;
}

interface ScatterTooltipProps {
  active?: boolean;
  payload?: ScatterTooltipPayloadEntry[];
}

function ScatterTooltip({ active, payload }: ScatterTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0]?.payload;
  if (!point) {
    return null;
  }
  return (
    <div className="rounded-card border border-line bg-surface px-3 py-2 text-xs shadow-card">
      <p className="font-semibold text-ink">
        {point.ticker} -- {point.verdict}
      </p>
      <p className="mt-1 text-muted">Conviction: {point.conviction_score} / 10</p>
      <p className="mt-0.5 text-muted">
        {point.price_change_pct >= 0 ? "+" : ""}
        {point.price_change_pct.toFixed(1)}% move
      </p>
    </div>
  );
}

/** Renders one point per evaluated verdict: conviction score vs. actual price-change outcome. */
export function ConvictionAccuracyScatterChart({
  entries,
}: ConvictionAccuracyScatterChartProps): JSX.Element {
  const { correct, incorrect } = toEvaluatedPoints(entries);
  const hasData = correct.length > 0 || incorrect.length > 0;

  return (
    <Card data-testid="conviction-accuracy-scatter-chart">
      <Card.Header>
        <Card.Title>Conviction vs. outcome</Card.Title>
      </Card.Header>
      {!hasData ? (
        <p className="text-sm text-muted">
          No verdicts have been scored yet -- this chart fills in once evaluations complete.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ScatterChart margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
            <XAxis
              type="number"
              dataKey="conviction_score"
              name="Conviction"
              domain={[1, 10]}
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              label={{
                value: "Conviction score",
                position: "insideBottom",
                offset: -4,
                fontSize: 11,
                fill: CHART_COLORS.muted,
              }}
            />
            <YAxis
              type="number"
              dataKey="price_change_pct"
              name="Price change"
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              width={48}
              tickFormatter={(value: number) => `${value}%`}
            />
            <ReferenceLine y={0} stroke={CHART_COLORS.muted} strokeDasharray="3 3" />
            <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: "3 3" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Scatter name="Correct" data={correct} fill={CHART_COLORS.buy} />
            <Scatter name="Incorrect" data={incorrect} fill={CHART_COLORS.sell} />
          </ScatterChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
