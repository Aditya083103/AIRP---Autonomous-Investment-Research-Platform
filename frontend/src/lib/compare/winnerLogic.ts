// frontend/src/lib/compare/winnerLogic.ts
// AIRP -- Compare page winner logic (T-064)
//
// Turns two already-fetched InvestmentDecisionResponse +
// AnalysisChartDataResponse pairs into the row list ComparisonTable.tsx
// renders. Deliberately a pure function with no React and no network
// calls -- given the exact same two decisions/chart payloads, it
// always returns the exact same rows and winners, which is what makes
// "winner logic correct" (the T-064 acceptance criterion) checkable
// directly in winnerLogic.test.ts without rendering anything or
// mocking fetch/WebSocket.
//
// Direction convention
// ---------------------
// Every numeric metric has a fixed "better direction" that does not
// depend on the companies being compared -- e.g. a lower P/E ratio is
// conventionally "cheaper" and therefore favourable, while a higher
// conviction score is always more favourable. That direction is data,
// not something inferred at comparison time, so METRIC_DEFINITIONS
// below encodes it once per row rather than recomputing it.
//
// Null handling
// -------------
// backend.routers.analysis's GET /charts endpoint already documents
// that valuation/sentiment/risk/financials can independently be
// null/empty per company (see AnalysisChartDataResponse's docstring in
// src/types/analysis.ts) -- a row whose value is missing for either
// company renders "--" for that side and never declares a winner: a
// missing data point is not evidence that the other company is
// better, so `winner` is `null` whenever either side is `null`.

import {
  type AnalysisChartDataResponse,
  type InvestmentDecisionResponse,
  type Verdict,
} from "@/types/analysis";

/** Which side wins a comparison row, or `null` if the row does not (or cannot) declare one. */
export type MetricWinner = "a" | "b" | "tie" | null;

/** A single rendered row of the comparison table. */
export interface ComparisonRow {
  /** Stable identifier, also used as the React key. */
  id: string;
  label: string;
  displayA: string;
  displayB: string;
  winner: MetricWinner;
}

type Direction = "higher" | "lower";

const VERDICT_RANK: Record<Verdict, number> = { SELL: 0, HOLD: 1, BUY: 2 };

/**
 * Compares two nullable numbers in the given direction.
 *
 * Returns `null` (no winner declared) if either value is missing, so a
 * gap in one company's data never gets silently read as a loss for
 * that company.
 */
export function compareNumeric(
  valueA: number | null,
  valueB: number | null,
  direction: Direction,
): MetricWinner {
  if (valueA === null || valueB === null) {
    return null;
  }
  if (valueA === valueB) {
    return "tie";
  }
  const aIsBetter = direction === "higher" ? valueA > valueB : valueA < valueB;
  return aIsBetter ? "a" : "b";
}

/** BUY beats HOLD beats SELL; equal verdicts tie. */
export function compareVerdict(verdictA: Verdict, verdictB: Verdict): MetricWinner {
  return compareNumeric(VERDICT_RANK[verdictA], VERDICT_RANK[verdictB], "higher");
}

/** Formats a nullable number for display, or "--" if missing. */
export function formatMetricValue(
  value: number | null,
  options: { decimals?: number; prefix?: string; suffix?: string } = {},
): string {
  if (value === null) {
    return "--";
  }
  const { decimals = 2, prefix = "", suffix = "" } = options;
  return `${prefix}${value.toFixed(decimals)}${suffix}`;
}

/** Most recent fiscal year's value for a given financials field, or `null` if unavailable. */
function latestFinancialValue(
  financials: AnalysisChartDataResponse["financials"],
  key: "revenue_crores" | "net_income_crores",
): number | null {
  for (let index = financials.length - 1; index >= 0; index -= 1) {
    const point = financials[index];
    if (point && point[key] !== null) {
      return point[key];
    }
  }
  return null;
}

export interface CompanySide {
  decision: InvestmentDecisionResponse;
  charts: AnalysisChartDataResponse;
}

/**
 * Builds every comparison row for the Compare page table from two
 * completed analyses. Row order is fixed: verdict and conviction first
 * (the headline call), then valuation, then sentiment/risk, then the
 * latest fundamentals -- roughly the same reading order
 * AnalysisResultPage.tsx already uses for a single company.
 */
export function buildComparisonRows(companyA: CompanySide, companyB: CompanySide): ComparisonRow[] {
  const { decision: decisionA, charts: chartsA } = companyA;
  const { decision: decisionB, charts: chartsB } = companyB;

  const revenueA = latestFinancialValue(chartsA.financials, "revenue_crores");
  const revenueB = latestFinancialValue(chartsB.financials, "revenue_crores");
  const netIncomeA = latestFinancialValue(chartsA.financials, "net_income_crores");
  const netIncomeB = latestFinancialValue(chartsB.financials, "net_income_crores");

  return [
    {
      id: "verdict",
      label: "Verdict",
      displayA: decisionA.verdict,
      displayB: decisionB.verdict,
      winner: compareVerdict(decisionA.verdict, decisionB.verdict),
    },
    {
      id: "conviction_score",
      label: "Conviction score",
      displayA: formatMetricValue(decisionA.conviction_score, { decimals: 0, suffix: "/10" }),
      displayB: formatMetricValue(decisionB.conviction_score, { decimals: 0, suffix: "/10" }),
      winner: compareNumeric(decisionA.conviction_score, decisionB.conviction_score, "higher"),
    },
    {
      id: "price_target",
      label: "Price target",
      displayA: decisionA.price_target ?? "--",
      displayB: decisionB.price_target ?? "--",
      // Free-text field (e.g. "₹1,800 (12-month)") -- not parsed into a
      // comparable number, so this row is informational only.
      winner: null,
    },
    {
      id: "pe_ratio",
      label: "P/E ratio",
      displayA: formatMetricValue(chartsA.valuation?.pe_ratio ?? null),
      displayB: formatMetricValue(chartsB.valuation?.pe_ratio ?? null),
      winner: compareNumeric(
        chartsA.valuation?.pe_ratio ?? null,
        chartsB.valuation?.pe_ratio ?? null,
        "lower",
      ),
    },
    {
      id: "pb_ratio",
      label: "P/B ratio",
      displayA: formatMetricValue(chartsA.valuation?.pb_ratio ?? null),
      displayB: formatMetricValue(chartsB.valuation?.pb_ratio ?? null),
      winner: compareNumeric(
        chartsA.valuation?.pb_ratio ?? null,
        chartsB.valuation?.pb_ratio ?? null,
        "lower",
      ),
    },
    {
      id: "ev_ebitda",
      label: "EV/EBITDA",
      displayA: formatMetricValue(chartsA.valuation?.ev_ebitda ?? null),
      displayB: formatMetricValue(chartsB.valuation?.ev_ebitda ?? null),
      winner: compareNumeric(
        chartsA.valuation?.ev_ebitda ?? null,
        chartsB.valuation?.ev_ebitda ?? null,
        "lower",
      ),
    },
    {
      id: "sentiment_score",
      label: "News sentiment",
      displayA: formatMetricValue(chartsA.sentiment?.sentiment_score ?? null),
      displayB: formatMetricValue(chartsB.sentiment?.sentiment_score ?? null),
      winner: compareNumeric(
        chartsA.sentiment?.sentiment_score ?? null,
        chartsB.sentiment?.sentiment_score ?? null,
        "higher",
      ),
    },
    {
      id: "risk_score",
      label: "Risk score",
      displayA: formatMetricValue(chartsA.risk?.risk_score ?? null),
      displayB: formatMetricValue(chartsB.risk?.risk_score ?? null),
      winner: compareNumeric(
        chartsA.risk?.risk_score ?? null,
        chartsB.risk?.risk_score ?? null,
        "lower",
      ),
    },
    {
      id: "latest_revenue",
      label: "Latest revenue (\u20b9 Cr)",
      displayA: formatMetricValue(revenueA, { decimals: 0 }),
      displayB: formatMetricValue(revenueB, { decimals: 0 }),
      winner: compareNumeric(revenueA, revenueB, "higher"),
    },
    {
      id: "latest_net_income",
      label: "Latest net income (\u20b9 Cr)",
      displayA: formatMetricValue(netIncomeA, { decimals: 0 }),
      displayB: formatMetricValue(netIncomeB, { decimals: 0 }),
      winner: compareNumeric(netIncomeA, netIncomeB, "higher"),
    },
  ];
}
