// frontend/src/components/charts/RevenueProfitChart.tsx
// AIRP -- Revenue/profit trend chart (T-062)
//
// Up to 4 years of annual revenue vs net income, grouped bars per
// fiscal year. Values are in INR Crores (backend.tools.financials
// normalises every company's reporting currency to Crores already --
// see that module's docstring), so this chart never needs its own
// currency-conversion logic.

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
import { type RevenueProfitPointResponse } from "@/types/analysis";

export interface RevenueProfitChartProps {
  financials: RevenueProfitPointResponse[];
}

function formatCrores(value: number): string {
  return `\u20B9${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
}

/** Renders a grouped bar chart of annual revenue vs net income (INR Crores). */
export function RevenueProfitChart({ financials }: RevenueProfitChartProps): JSX.Element {
  return (
    <Card data-testid="revenue-profit-chart">
      <Card.Header>
        <Card.Title>Revenue &amp; profit trend</Card.Title>
      </Card.Header>
      {financials.length === 0 ? (
        <p className="text-sm text-muted">
          Revenue and profit trend data was not available for this analysis.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={financials} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.line} />
            <XAxis dataKey="fiscal_year" tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
            <YAxis
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              width={64}
              tickFormatter={(value: number) => value.toLocaleString("en-IN")}
            />
            <Tooltip formatter={(value: number) => formatCrores(value)} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar
              dataKey="revenue_crores"
              name="Revenue"
              fill={CHART_COLORS.brand}
              radius={[4, 4, 0, 0]}
            />
            <Bar
              dataKey="net_income_crores"
              name="Net income"
              fill={CHART_COLORS.buy}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
