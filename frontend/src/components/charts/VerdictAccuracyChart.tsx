// frontend/src/components/charts/VerdictAccuracyChart.tsx
// AIRP -- Accuracy-by-verdict-type bar chart (T-092)
//
// One bar per BUY/HOLD/SELL, height = that verdict's accuracy_pct from
// GET /api/v1/accuracy/summary's by_verdict breakdown (T-091).
// backend.services.accuracy_tracker.get_accuracy_summary guarantees all
// three verdicts are always present in that array, even with zero
// scored rows for one of them (see that function's own docstring) -- so
// this chart never needs to backfill a missing verdict itself, only
// decide how to render a null accuracy_pct (see NOT_YET_SCORED_LABEL
// below) once it gets one.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type VerdictAccuracyBreakdownResponse } from "@/types/accuracy";
import { type Verdict } from "@/types/analysis";

export interface VerdictAccuracyChartProps {
  byVerdict: VerdictAccuracyBreakdownResponse[];
}

const VERDICT_COLORS: Record<Verdict, string> = {
  BUY: CHART_COLORS.buy,
  HOLD: CHART_COLORS.hold,
  SELL: CHART_COLORS.sell,
};

/** Shown for a verdict with zero evaluated rows -- an unknown, not a 0%, accuracy. */
const NOT_YET_SCORED_LABEL = "Not yet scored";

interface VerdictBarRow {
  verdict: Verdict;
  /** 0 when accuracy_pct is null (nothing scored) so the bar renders at zero height, not a gap. */
  accuracy_pct: number;
  evaluated_count: number;
  has_data: boolean;
}

function toBarRows(byVerdict: VerdictAccuracyBreakdownResponse[]): VerdictBarRow[] {
  return byVerdict.map((entry) => ({
    verdict: entry.verdict,
    accuracy_pct: entry.accuracy_pct ?? 0,
    evaluated_count: entry.evaluated_count,
    has_data: entry.accuracy_pct !== null,
  }));
}

interface VerdictTooltipPayloadEntry {
  payload?: VerdictBarRow;
}

interface VerdictTooltipProps {
  active?: boolean;
  payload?: VerdictTooltipPayloadEntry[];
}

function VerdictTooltip({ active, payload }: VerdictTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const row = payload[0]?.payload;
  if (!row) {
    return null;
  }
  return (
    <div className="rounded-card border border-line bg-surface px-3 py-2 text-xs shadow-card">
      <p className="font-semibold text-ink">{row.verdict}</p>
      <p className="mt-1 text-muted">
        {row.has_data ? `${row.accuracy_pct.toFixed(1)}% accurate` : NOT_YET_SCORED_LABEL}
      </p>
      <p className="mt-0.5 text-muted">{row.evaluated_count} scored</p>
    </div>
  );
}

/** Renders one accuracy-percentage bar per BUY/HOLD/SELL verdict, colour-matched to the verdict. */
export function VerdictAccuracyChart({ byVerdict }: VerdictAccuracyChartProps): JSX.Element {
  const rows = toBarRows(byVerdict);
  const anyScored = rows.some((row) => row.has_data);

  return (
    <Card data-testid="verdict-accuracy-chart">
      <Card.Header>
        <Card.Title>Accuracy by verdict type</Card.Title>
      </Card.Header>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">Verdict accuracy data was not available.</p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
              <XAxis dataKey="verdict" tick={{ fontSize: 12, fill: CHART_COLORS.muted }} />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
                width={40}
                tickFormatter={(value: number) => `${value}%`}
              />
              <Tooltip content={<VerdictTooltip />} />
              <Bar dataKey="accuracy_pct" radius={[4, 4, 0, 0]}>
                {rows.map((row) => (
                  <Cell key={row.verdict} fill={VERDICT_COLORS[row.verdict]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          {!anyScored ? (
            <p className="mt-2 text-sm text-muted">
              No verdicts have been scored yet for any type -- bars will fill in as evaluations
              complete.
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}
