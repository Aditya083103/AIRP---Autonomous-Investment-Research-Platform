// frontend/src/components/charts/StockPriceChart.tsx
// AIRP -- Stock price chart (T-062)
//
// 1-year daily closing price line/area chart. Deliberately an area
// (not candlestick) chart -- InvestmentDecisionResponse-adjacent chart
// data only carries close/volume per day (see PricePointResponse and
// backend.models.schemas's own docstring on why), and a filled area
// under a single price line is the more legible choice for a portfolio
// dashboard than trying to squeeze open/high/low into a chart that
// only has a close value for context anyway.

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type PricePointResponse } from "@/types/analysis";

export interface StockPriceChartProps {
  ticker: string;
  currency: string;
  pricePoints: PricePointResponse[];
}

interface PriceTooltipPayloadEntry {
  value?: number;
  payload?: { date?: string };
}

interface PriceTooltipProps {
  active?: boolean;
  payload?: PriceTooltipPayloadEntry[];
  currency: string;
}

function formatDateTick(dateStr: string): string {
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) {
    return dateStr;
  }
  return parsed.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

function formatCurrency(value: number, currency: string): string {
  return `${currency === "INR" ? "\u20B9" : currency + " "}${value.toLocaleString("en-IN")}`;
}

function PriceTooltip({ active, payload, currency }: PriceTooltipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0];
  if (!point || typeof point.value !== "number") {
    return null;
  }
  const label = point.payload?.date;
  return (
    <div className="rounded-card border border-line bg-surface px-3 py-2 text-xs shadow-card">
      <p className="font-mono text-muted">{label ?? ""}</p>
      <p className="mt-1 font-semibold text-ink">{formatCurrency(point.value, currency)}</p>
    </div>
  );
}

/** Renders a 1-year daily closing-price area chart for the analysed ticker. */
export function StockPriceChart({
  ticker,
  currency,
  pricePoints,
}: StockPriceChartProps): JSX.Element {
  return (
    <Card data-testid="stock-price-chart">
      <Card.Header>
        <Card.Title>{ticker} -- 1-year price</Card.Title>
      </Card.Header>
      {pricePoints.length === 0 ? (
        <p className="text-sm text-muted">Price history was not available for this analysis.</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={pricePoints} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="stockPriceFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={CHART_COLORS.brand} stopOpacity={0.35} />
                <stop offset="95%" stopColor={CHART_COLORS.brand} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDateTick}
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              minTickGap={32}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              width={56}
              tickFormatter={(value: number) => value.toLocaleString("en-IN")}
            />
            <Tooltip content={<PriceTooltip currency={currency} />} />
            <Area
              type="monotone"
              dataKey="close"
              stroke={CHART_COLORS.brand}
              strokeWidth={2}
              fill="url(#stockPriceFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
