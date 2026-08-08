// frontend/src/components/charts/AccuracyTrendChart.tsx
// AIRP -- Rolling accuracy trend chart (T-092)
//
// Line chart of the Portfolio Manager's rolling directional-accuracy
// percentage over time, built from a page of
// GET /api/v1/accuracy/history (T-091) entries via
// src/lib/accuracy/rollingAccuracy.ts's buildRollingAccuracySeries --
// see that file's docstring for why a rolling window (not cumulative
// accuracy-to-date) is the right shape for "is the committee currently
// performing well", and why still-pending (unevaluated) verdicts are
// excluded before windowing.

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";
import { buildRollingAccuracySeries, ROLLING_WINDOW_SIZE } from "@/lib/accuracy/rollingAccuracy";
import { CHART_COLORS } from "@/lib/chartColors";
import { type AccuracyHistoryEntryResponse } from "@/types/accuracy";

export interface AccuracyTrendChartProps {
  entries: AccuracyHistoryEntryResponse[];
}

interface TrendTooltipPayloadEntry {
  value?: number;
  payload?: { verdict_date?: string; sample_size?: number };
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: TrendTooltipPayloadEntry[];
}

function formatDateTick(dateStr: string): string {
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) {
    return dateStr;
  }
  return parsed.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

function TrendTooltip({ active, payload }: TrendTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0];
  if (!point || typeof point.value !== "number") {
    return null;
  }
  const date = point.payload?.verdict_date;
  const sampleSize = point.payload?.sample_size;
  return (
    <div className="rounded-card border border-line bg-surface px-3 py-2 text-xs shadow-card">
      <p className="font-mono text-muted">{date ? formatDateTick(date) : ""}</p>
      <p className="mt-1 font-semibold text-ink">{point.value.toFixed(1)}% accurate</p>
      {typeof sampleSize === "number" ? (
        <p className="mt-0.5 text-muted">last {sampleSize} verdicts</p>
      ) : null}
    </div>
  );
}

/** Renders a rolling-window accuracy trend line from a page of accuracy history entries. */
export function AccuracyTrendChart({ entries }: AccuracyTrendChartProps): JSX.Element {
  const series = buildRollingAccuracySeries(entries);

  return (
    <Card data-testid="accuracy-trend-chart">
      <Card.Header>
        <Card.Title>Rolling accuracy trend</Card.Title>
      </Card.Header>
      {series.length === 0 ? (
        <p className="text-sm text-muted">
          No verdicts have been scored yet -- check back once the first evaluation horizon elapses.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
              <XAxis
                dataKey="verdict_date"
                tickFormatter={formatDateTick}
                tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
                minTickGap={32}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
                width={40}
                tickFormatter={(value: number) => `${value}%`}
              />
              <Tooltip content={<TrendTooltip />} />
              <Line
                type="monotone"
                dataKey="rolling_accuracy_pct"
                stroke={CHART_COLORS.brand}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="mt-2 font-mono text-xs text-muted">
            Rolling {ROLLING_WINDOW_SIZE}-verdict window, over {series.length} scored{" "}
            {series.length === 1 ? "verdict" : "verdicts"}
          </p>
        </>
      )}
    </Card>
  );
}
