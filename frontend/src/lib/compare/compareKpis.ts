// frontend/src/lib/compare/compareKpis.ts
// AIRP -- Compare page KPI card data (B11)
//
// Turns two completed CompanySide payloads (see winnerLogic.ts) into the
// handful of headline KPI cards CompareKpiRow.tsx renders above the full
// ComparisonTable -- verdict, conviction, a P/E valuation gap, risk
// score, and sentiment, each side by side. Deliberately separate from
// winnerLogic.ts's buildComparisonRows: that function's job is the
// exhaustive metric-by-metric table (every row, every winner), while
// this one picks just the handful of numbers worth a large, glanceable
// card treatment -- the same "headline vs. detail" split
// AnalysisResultPage.tsx already draws between ConvictionGauge (one
// number, large) and the full ChartsPanel (everything, detailed).

import { type CompanySide } from "@/lib/compare/winnerLogic";

export interface CompareKpi {
  id: string;
  label: string;
  valueA: string;
  valueB: string;
  /** Extra context shown under the two values, e.g. the P/E gap magnitude. */
  note?: string;
}

function formatNullableNumber(value: number | null | undefined, decimals = 2): string {
  return value === null || value === undefined ? "--" : value.toFixed(decimals);
}

/** Absolute P/E gap between the two companies, or null if either side's P/E is missing. */
function computeValuationGap(
  peA: number | null | undefined,
  peB: number | null | undefined,
): number | null {
  if (peA === null || peA === undefined || peB === null || peB === undefined) {
    return null;
  }
  return Math.abs(peA - peB);
}

/** Builds the Compare page's 5 headline KPI cards from two completed analyses. */
export function buildCompareKpis(sideA: CompanySide, sideB: CompanySide): CompareKpi[] {
  const peA = sideA.charts.valuation?.pe_ratio ?? null;
  const peB = sideB.charts.valuation?.pe_ratio ?? null;
  const valuationGap = computeValuationGap(peA, peB);

  return [
    {
      id: "verdict",
      label: "Verdict",
      valueA: sideA.decision.verdict,
      valueB: sideB.decision.verdict,
    },
    {
      id: "conviction",
      label: "Conviction",
      valueA: `${sideA.decision.conviction_score}/10`,
      valueB: `${sideB.decision.conviction_score}/10`,
    },
    {
      id: "valuation_gap",
      label: "Valuation (P/E)",
      valueA: formatNullableNumber(peA),
      valueB: formatNullableNumber(peB),
      ...(valuationGap !== null ? { note: `Gap: ${valuationGap.toFixed(2)}` } : {}),
    },
    {
      id: "risk_score",
      label: "Risk score",
      valueA: formatNullableNumber(sideA.charts.risk?.risk_score ?? null),
      valueB: formatNullableNumber(sideB.charts.risk?.risk_score ?? null),
    },
    {
      id: "sentiment",
      label: "News sentiment",
      valueA: formatNullableNumber(sideA.charts.sentiment?.sentiment_score ?? null),
      valueB: formatNullableNumber(sideB.charts.sentiment?.sentiment_score ?? null),
    },
  ];
}
