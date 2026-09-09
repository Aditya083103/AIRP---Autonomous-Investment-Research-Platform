// frontend/src/test/CompareKpiRow.test.tsx
// Tests for CompareKpiRow (B11).

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompareKpiRow } from "@/components/compare/CompareKpiRow";
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

describe("CompareKpiRow", () => {
  it("renders the container", () => {
    render(
      <CompareKpiRow
        companyNameA="TCS"
        companyNameB="Infosys"
        sideA={makeSide()}
        sideB={makeSide()}
      />,
    );
    expect(screen.getByTestId("compare-kpi-row")).toBeInTheDocument();
  });

  it("renders both companies' verdicts as badges", () => {
    render(
      <CompareKpiRow
        companyNameA="TCS"
        companyNameB="Infosys"
        sideA={makeSide({ verdict: "BUY" })}
        sideB={makeSide({ verdict: "SELL" })}
      />,
    );
    const row = screen.getByTestId("compare-kpi-row");
    expect(within(row).getByText("BUY")).toBeInTheDocument();
    expect(within(row).getByText("SELL")).toBeInTheDocument();
  });

  it("renders both companies' conviction scores", () => {
    render(
      <CompareKpiRow
        companyNameA="TCS"
        companyNameB="Infosys"
        sideA={makeSide({ conviction_score: 8 })}
        sideB={makeSide({ conviction_score: 3 })}
      />,
    );
    const row = screen.getByTestId("compare-kpi-row");
    expect(within(row).getByText("8/10")).toBeInTheDocument();
    expect(within(row).getByText("3/10")).toBeInTheDocument();
  });

  it("renders the valuation gap note when both sides have a P/E ratio", () => {
    render(
      <CompareKpiRow
        companyNameA="TCS"
        companyNameB="Infosys"
        sideA={makeSide({}, { valuation: makeValuation({ pe_ratio: 25 }) })}
        sideB={makeSide({}, { valuation: makeValuation({ pe_ratio: 18 }) })}
      />,
    );
    expect(screen.getByText("Gap: 7.00")).toBeInTheDocument();
  });

  it("renders both company names as labels for each KPI card", () => {
    render(
      <CompareKpiRow
        companyNameA="TCS"
        companyNameB="Infosys"
        sideA={makeSide()}
        sideB={makeSide()}
      />,
    );
    expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Infosys").length).toBeGreaterThan(0);
  });
});
