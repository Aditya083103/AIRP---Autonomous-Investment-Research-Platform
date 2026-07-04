// frontend/src/components/charts/RiskRadarChart.tsx
// AIRP -- Risk radar chart (T-062)
//
// RiskRadarResponse's 5 scores (overall + governance/regulatory/
// financial/concentration) plotted as a single radar/spider chart --
// every axis is 1 (low risk) to 10 (high risk) on the SAME scale
// already, so unlike PeerValuationChart this needs no normalisation,
// just a reshape from "one field per risk type" into the
// "one row per axis" RadarChart expects.

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { Card } from "@/components/ui";
import { CHART_COLORS } from "@/lib/chartColors";
import { type RiskRadarResponse } from "@/types/analysis";

export interface RiskRadarChartProps {
  risk: RiskRadarResponse | null;
}

interface RiskAxisRow {
  axis: string;
  value: number;
}

function buildAxisRows(risk: RiskRadarResponse): RiskAxisRow[] {
  return [
    { axis: "Overall", value: risk.risk_score },
    { axis: "Governance", value: risk.governance_risk },
    { axis: "Regulatory", value: risk.regulatory_risk },
    { axis: "Financial", value: risk.financial_risk },
    { axis: "Concentration", value: risk.concentration_risk },
  ];
}

/** Renders the Risk Officer's 5 risk scores (1-10 each) as a radar chart. */
export function RiskRadarChart({ risk }: RiskRadarChartProps): JSX.Element {
  return (
    <Card data-testid="risk-radar-chart">
      <Card.Header>
        <Card.Title>Risk profile</Card.Title>
      </Card.Header>
      {risk === null ? (
        <p className="text-sm text-muted">Risk data was not available for this analysis.</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <RadarChart data={buildAxisRows(risk)} outerRadius="72%">
            <PolarGrid stroke={CHART_COLORS.line} />
            <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 10]}
              tick={{ fontSize: 10, fill: CHART_COLORS.muted }}
            />
            <Radar
              dataKey="value"
              stroke={CHART_COLORS.sell}
              fill={CHART_COLORS.sell}
              fillOpacity={0.25}
            />
            <Tooltip formatter={(value: number) => `${value} / 10`} />
          </RadarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}
