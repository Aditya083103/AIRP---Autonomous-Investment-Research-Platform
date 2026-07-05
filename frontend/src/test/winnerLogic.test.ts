// frontend/src/test/winnerLogic.test.ts
// Tests for src/lib/compare/winnerLogic.ts (T-064). compareNumeric,
// compareVerdict, and buildComparisonRows are all pure functions, so
// these tests assert their output directly against hand-built
// InvestmentDecisionResponse / AnalysisChartDataResponse fixtures --
// no rendering, no network, no mocking. This is the direct check for
// the "winner logic correct" acceptance criterion.

import { describe, expect, it } from "vitest";

import {
  buildComparisonRows,
  compareNumeric,
  compareVerdict,
  formatMetricValue,
  type CompanySide,
} from "@/lib/compare/winnerLogic";
import { type AnalysisChartDataResponse, type InvestmentDecisionResponse } from "@/types/analysis";

function makeDecision(
  overrides: Partial<InvestmentDecisionResponse> = {},
): InvestmentDecisionResponse {
  return {
    agent_name: "portfolio_manager",
    analysis_id: "job-1",
    company_name: "Company A",
    ticker: "AAA.NS",
    generated_at: "2026-06-15T10:30:00Z",
    error: null,
    verdict: "BUY",
    conviction_score: 8,
    price_target: "\u20b91,800 (12-month)",
    time_horizon: "12 months",
    executive_summary: "",
    investment_thesis: "",
    bull_case: "",
    bear_case: "",
    risk_summary: "",
    valuation_summary: "",
    key_risks: [],
    key_catalysts: [],
    contrarian_response: "",
    debate_rounds_used: 2,
    agent_weights: {},
    summary: "",
    ...overrides,
  };
}

function makeCharts(overrides: Partial<AnalysisChartDataResponse> = {}): AnalysisChartDataResponse {
  return {
    job_id: "job-1",
    ticker: "AAA.NS",
    company_name: "Company A",
    price_currency: "INR",
    price_history: [],
    financials: [],
    valuation: null,
    sentiment: null,
    risk: null,
    data_warnings: [],
    ...overrides,
  };
}

describe("compareNumeric", () => {
  it("declares the higher value the winner when direction is 'higher'", () => {
    expect(compareNumeric(8, 5, "higher")).toBe("a");
    expect(compareNumeric(5, 8, "higher")).toBe("b");
  });

  it("declares the lower value the winner when direction is 'lower'", () => {
    expect(compareNumeric(15, 25, "lower")).toBe("a");
    expect(compareNumeric(25, 15, "lower")).toBe("b");
  });

  it("returns 'tie' for equal values", () => {
    expect(compareNumeric(10, 10, "higher")).toBe("tie");
    expect(compareNumeric(10, 10, "lower")).toBe("tie");
  });

  it("returns null when either value is missing, in either direction", () => {
    expect(compareNumeric(null, 5, "higher")).toBeNull();
    expect(compareNumeric(5, null, "higher")).toBeNull();
    expect(compareNumeric(null, null, "lower")).toBeNull();
  });
});

describe("compareVerdict", () => {
  it("ranks BUY above HOLD and SELL", () => {
    expect(compareVerdict("BUY", "HOLD")).toBe("a");
    expect(compareVerdict("BUY", "SELL")).toBe("a");
  });

  it("ranks HOLD above SELL", () => {
    expect(compareVerdict("HOLD", "SELL")).toBe("a");
    expect(compareVerdict("SELL", "HOLD")).toBe("b");
  });

  it("ties identical verdicts", () => {
    expect(compareVerdict("HOLD", "HOLD")).toBe("tie");
  });
});

describe("formatMetricValue", () => {
  it("renders '--' for a null value", () => {
    expect(formatMetricValue(null)).toBe("--");
  });

  it("formats a number to 2 decimals by default", () => {
    expect(formatMetricValue(23.456)).toBe("23.46");
  });

  it("honours custom decimals, prefix, and suffix", () => {
    expect(formatMetricValue(8, { decimals: 0, suffix: "/10" })).toBe("8/10");
  });
});

describe("buildComparisonRows", () => {
  it("includes a verdict row with the correct winner", () => {
    const companyA: CompanySide = {
      decision: makeDecision({ verdict: "BUY" }),
      charts: makeCharts(),
    };
    const companyB: CompanySide = {
      decision: makeDecision({ verdict: "SELL", company_name: "Company B" }),
      charts: makeCharts({ company_name: "Company B" }),
    };

    const rows = buildComparisonRows(companyA, companyB);
    const verdictRow = rows.find((row) => row.id === "verdict");

    expect(verdictRow).toBeDefined();
    expect(verdictRow?.displayA).toBe("BUY");
    expect(verdictRow?.displayB).toBe("SELL");
    expect(verdictRow?.winner).toBe("a");
  });

  it("picks the lower P/E ratio as the valuation winner", () => {
    const valuationBase = {
      sector_avg_pe: 20,
      pb_ratio: null,
      sector_avg_pb: null,
      ev_ebitda: null,
      sector_avg_ev_ebitda: null,
      peer_tickers: [],
    };
    const companyA: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({ valuation: { ...valuationBase, pe_ratio: 18 } }),
    };
    const companyB: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({ valuation: { ...valuationBase, pe_ratio: 28 } }),
    };

    const rows = buildComparisonRows(companyA, companyB);
    const peRow = rows.find((row) => row.id === "pe_ratio");

    expect(peRow?.winner).toBe("a");
    expect(peRow?.displayA).toBe("18.00");
    expect(peRow?.displayB).toBe("28.00");
  });

  it("never declares a winner for a metric missing on either side", () => {
    const companyA: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({ valuation: null }),
    };
    const companyB: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({ valuation: null }),
    };

    const rows = buildComparisonRows(companyA, companyB);
    const peRow = rows.find((row) => row.id === "pe_ratio");

    expect(peRow?.winner).toBeNull();
    expect(peRow?.displayA).toBe("--");
    expect(peRow?.displayB).toBe("--");
  });

  it("never declares a winner for the free-text price target row", () => {
    const companyA: CompanySide = {
      decision: makeDecision({ price_target: "\u20b91,000" }),
      charts: makeCharts(),
    };
    const companyB: CompanySide = {
      decision: makeDecision({ price_target: "\u20b92,000" }),
      charts: makeCharts(),
    };

    const rows = buildComparisonRows(companyA, companyB);
    const priceTargetRow = rows.find((row) => row.id === "price_target");

    expect(priceTargetRow?.winner).toBeNull();
  });

  it("compares latest revenue using the most recent non-null fiscal year", () => {
    const companyA: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({
        financials: [
          { fiscal_year: "FY24", revenue_crores: 1000, net_income_crores: 100 },
          { fiscal_year: "FY25", revenue_crores: 1200, net_income_crores: 150 },
        ],
      }),
    };
    const companyB: CompanySide = {
      decision: makeDecision(),
      charts: makeCharts({
        financials: [
          { fiscal_year: "FY24", revenue_crores: 900, net_income_crores: 80 },
          { fiscal_year: "FY25", revenue_crores: null, net_income_crores: null },
        ],
      }),
    };

    const rows = buildComparisonRows(companyA, companyB);
    const revenueRow = rows.find((row) => row.id === "latest_revenue");

    // Company B's latest (FY25) revenue is null, so the most recent
    // non-null fiscal year (FY24, 900) is used instead of treating the
    // metric as entirely missing.
    expect(revenueRow?.winner).toBe("a");
    expect(revenueRow?.displayA).toBe("1200");
    expect(revenueRow?.displayB).toBe("900");
  });

  it("returns the same number and order of rows regardless of company order", () => {
    const companyA: CompanySide = { decision: makeDecision(), charts: makeCharts() };
    const companyB: CompanySide = { decision: makeDecision(), charts: makeCharts() };

    const rowsAB = buildComparisonRows(companyA, companyB);
    const rowsBA = buildComparisonRows(companyB, companyA);

    expect(rowsAB.map((row) => row.id)).toEqual(rowsBA.map((row) => row.id));
  });
});
