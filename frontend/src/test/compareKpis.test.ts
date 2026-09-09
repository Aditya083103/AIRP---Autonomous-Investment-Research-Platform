// frontend/src/test/compareKpis.test.ts
// Tests for src/lib/compare/compareKpis.ts (B11). Pure-function tests
// with plain fixture payloads -- mirrors src/test/winnerLogic.test.ts's
// own "computation separate from rendering" test style.

import { describe, expect, it } from "vitest";

import { buildCompareKpis } from "@/lib/compare/compareKpis";
import { type CompanySide } from "@/lib/compare/winnerLogic";
import {
  type AnalysisChartDataResponse,
  type InvestmentDecisionResponse,
  type ValuationChartResponse,
} from "@/types/analysis";

function makeDecision(
  overrides: Partial<InvestmentDecisionResponse> = {},
): InvestmentDecisionResponse {
  return {
    agent_name: "portfolio_manager",
    analysis_id: "job-a",
    company_name: "Tata Consultancy Services",
    ticker: "TCS.NS",
    generated_at: "2026-06-15T10:30:00Z",
    error: null,
    verdict: "BUY",
    conviction_score: 8,
    price_target: null,
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
    fundamental_years_available: null,
    ...overrides,
  };
}

function makeValuation(overrides: Partial<ValuationChartResponse> = {}): ValuationChartResponse {
  return {
    pe_ratio: null,
    sector_avg_pe: null,
    pb_ratio: null,
    sector_avg_pb: null,
    ev_ebitda: null,
    sector_avg_ev_ebitda: null,
    peer_tickers: [],
    ...overrides,
  };
}

function makeCharts(overrides: Partial<AnalysisChartDataResponse> = {}): AnalysisChartDataResponse {
  return {
    job_id: "job-a",
    ticker: "TCS.NS",
    company_name: "Tata Consultancy Services",
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

function makeSide(
  decisionOverrides: Partial<InvestmentDecisionResponse> = {},
  chartsOverrides: Partial<AnalysisChartDataResponse> = {},
): CompanySide {
  return { decision: makeDecision(decisionOverrides), charts: makeCharts(chartsOverrides) };
}

describe("buildCompareKpis", () => {
  it("returns verdict and conviction for both sides", () => {
    const sideA = makeSide({ verdict: "BUY", conviction_score: 8 });
    const sideB = makeSide({ verdict: "SELL", conviction_score: 3 });

    const kpis = buildCompareKpis(sideA, sideB);

    expect(kpis.find((kpi) => kpi.id === "verdict")).toMatchObject({
      valueA: "BUY",
      valueB: "SELL",
    });
    expect(kpis.find((kpi) => kpi.id === "conviction")).toMatchObject({
      valueA: "8/10",
      valueB: "3/10",
    });
  });

  it("computes the P/E valuation gap when both sides have a P/E ratio", () => {
    const sideA = makeSide({}, { valuation: makeValuation({ pe_ratio: 25 }) });
    const sideB = makeSide({}, { valuation: makeValuation({ pe_ratio: 18 }) });

    const kpi = buildCompareKpis(sideA, sideB).find((entry) => entry.id === "valuation_gap");

    expect(kpi).toMatchObject({ valueA: "25.00", valueB: "18.00", note: "Gap: 7.00" });
  });

  it("shows '--' and no gap note when either side's P/E ratio is missing", () => {
    const sideA = makeSide({}, { valuation: makeValuation({ pe_ratio: 25 }) });
    const sideB = makeSide({}, { valuation: null });

    const kpi = buildCompareKpis(sideA, sideB).find((entry) => entry.id === "valuation_gap");

    expect(kpi?.valueB).toBe("--");
    expect(kpi?.note).toBeUndefined();
  });

  it("shows '--' for risk score and sentiment when missing", () => {
    const sideA = makeSide({}, { risk: null, sentiment: null });
    const sideB = makeSide({}, { risk: null, sentiment: null });

    const kpis = buildCompareKpis(sideA, sideB);

    expect(kpis.find((kpi) => kpi.id === "risk_score")).toMatchObject({
      valueA: "--",
      valueB: "--",
    });
    expect(kpis.find((kpi) => kpi.id === "sentiment")).toMatchObject({
      valueA: "--",
      valueB: "--",
    });
  });

  it("returns exactly 5 KPI cards in a stable order", () => {
    const kpis = buildCompareKpis(makeSide(), makeSide());
    expect(kpis.map((kpi) => kpi.id)).toEqual([
      "verdict",
      "conviction",
      "valuation_gap",
      "risk_score",
      "sentiment",
    ]);
  });
});
