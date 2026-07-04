// frontend/src/test/ChartsPanel.test.tsx
// Tests for ChartsPanel (T-062) -- the top-level composition of all 5
// T-062 charts. Each chart's own test file already covers its
// individual rendering/fallback behaviour in depth; this file's job is
// to confirm every chart is actually wired into the panel and that
// data_warnings surfaces above them, not to re-test each chart's
// internals.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChartsPanel } from "@/components/charts/ChartsPanel";
import { type AnalysisChartDataResponse } from "@/types/analysis";

function makeChartData(
  overrides: Partial<AnalysisChartDataResponse> = {},
): AnalysisChartDataResponse {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    ticker: "TCS.NS",
    company_name: "Tata Consultancy Services",
    price_currency: "INR",
    price_history: [{ date: "2026-06-18", close: 3845.2, volume: 1_204_500 }],
    financials: [
      { fiscal_year: "FY 2024", revenue_crores: 240_890.5, net_income_crores: 45_868.0 },
    ],
    valuation: {
      pe_ratio: 28.4,
      sector_avg_pe: 24.1,
      pb_ratio: 11.2,
      sector_avg_pb: 9.8,
      ev_ebitda: 19.6,
      sector_avg_ev_ebitda: 17.3,
      peer_tickers: ["INFY.NS"],
    },
    sentiment: {
      sentiment_score: 0.42,
      sentiment_label: "positive",
      articles_analysed: 24,
      positive_articles: 14,
      negative_articles: 3,
      neutral_articles: 7,
    },
    risk: {
      risk_score: 4,
      governance_risk: 3,
      regulatory_risk: 2,
      financial_risk: 5,
      concentration_risk: 6,
    },
    data_warnings: [],
    ...overrides,
  };
}

describe("ChartsPanel", () => {
  it("renders all 5 charts", () => {
    render(<ChartsPanel data={makeChartData()} />);
    expect(screen.getByTestId("stock-price-chart")).toBeInTheDocument();
    expect(screen.getByTestId("revenue-profit-chart")).toBeInTheDocument();
    expect(screen.getByTestId("peer-valuation-chart")).toBeInTheDocument();
    expect(screen.getByTestId("sentiment-gauge-chart")).toBeInTheDocument();
    expect(screen.getByTestId("risk-radar-chart")).toBeInTheDocument();
  });

  it("does not show a warnings banner when data_warnings is empty", () => {
    render(<ChartsPanel data={makeChartData({ data_warnings: [] })} />);
    expect(screen.queryByTestId("charts-panel-warnings")).not.toBeInTheDocument();
  });

  it("shows a warnings banner listing every data_warnings entry", () => {
    render(
      <ChartsPanel
        data={makeChartData({
          data_warnings: [
            "Valuation data was not available for this analysis.",
            "Price history unavailable: rate limited",
          ],
        })}
      />,
    );
    const banner = screen.getByTestId("charts-panel-warnings");
    expect(banner).toHaveTextContent("Valuation data was not available for this analysis.");
    expect(banner).toHaveTextContent("Price history unavailable: rate limited");
  });

  it("renders the fallback state for a null chart source alongside populated ones", () => {
    render(<ChartsPanel data={makeChartData({ valuation: null })} />);
    expect(
      screen.getByText("Peer valuation data was not available for this analysis."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("sentiment-gauge-chart")).toBeInTheDocument();
    expect(screen.getByTestId("risk-radar-chart")).toBeInTheDocument();
  });
});
