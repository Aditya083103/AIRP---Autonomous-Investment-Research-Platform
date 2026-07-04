// frontend/src/components/charts/PeerValuationChart.tsx
// AIRP -- P/E-vs-peers valuation chart (T-062)
//
// ValuationChartResponse carries the company's own multiple next to
// the sector average for three ratios (P/E, P/B, EV/EBITDA) -- this
// chart reshapes that "one row per metric" response into "one row per
// company/sector pair" the grouped BarChart Recharts expects, and
// drops any metric where BOTH the company and sector value are
// missing (rather than rendering an empty pair of bars for it).

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type ValuationChartResponse } from "@/types/analysis";

export interface PeerValuationChartProps {
  valuation: ValuationChartResponse | null;
}

interface ValuationMetricRow {
  metric: string;
  company: number | null;
  sector: number | null;
}

function buildMetricRows(valuation: ValuationChartResponse): ValuationMetricRow[] {
  const rows: ValuationMetricRow[] = [
    { metric: "P/E", company: valuation.pe_ratio, sector: valuation.sector_avg_pe },
    { metric: "P/B", company: valuation.pb_ratio, sector: valuation.sector_avg_pb },
    {
      metric: "EV/EBITDA",
      company: valuation.ev_ebitda,
      sector: valuation.sector_avg_ev_ebitda,
    },
  ];
  return rows.filter((row) => row.company !== null || row.sector !== null);
}

/** Renders the company's P/E, P/B, and EV/EBITDA multiples against sector averages. */
export function PeerValuationChart({ valuation }: PeerValuationChartProps): JSX.Element {
  const rows = valuation ? buildMetricRows(valuation) : [];

  return (
    <Card data-testid="peer-valuation-chart">
      <Card.Header>
        <Card.Title>Valuation vs peers</Card.Title>
      </Card.Header>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">
          Peer valuation data was not available for this analysis.
        </p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
              <XAxis dataKey="metric" tick={{ fontSize: 12, fill: CHART_COLORS.muted }} />
              <YAxis tick={{ fontSize: 11, fill: CHART_COLORS.muted }} width={40} />
              <Tooltip formatter={(value: number) => value.toFixed(1)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar
                dataKey="company"
                name="Company"
                fill={CHART_COLORS.brand}
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="sector"
                name="Sector avg"
                fill={CHART_COLORS.muted}
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
          {valuation && valuation.peer_tickers.length > 0 ? (
            <p className="mt-2 font-mono text-xs text-muted">
              Peers: {valuation.peer_tickers.join(", ")}
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}
