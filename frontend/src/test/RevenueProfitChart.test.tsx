// frontend/src/test/RevenueProfitChart.test.tsx
// Tests for RevenueProfitChart (T-062). See StockPriceChart.test.tsx's
// docstring for why these tests focus on title/fallback/container
// rather than Recharts' own internal SVG output.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RevenueProfitChart } from "@/components/charts/RevenueProfitChart";
import { type RevenueProfitPointResponse } from "@/types/analysis";

const SAMPLE_FINANCIALS: RevenueProfitPointResponse[] = [
  { fiscal_year: "FY 2023", revenue_crores: 225_458.0, net_income_crores: 42_147.0 },
  { fiscal_year: "FY 2024", revenue_crores: 240_890.5, net_income_crores: 45_868.0 },
];

describe("RevenueProfitChart", () => {
  it("renders the chart title", () => {
    render(<RevenueProfitChart financials={SAMPLE_FINANCIALS} />);
    expect(screen.getByText("Revenue & profit trend")).toBeInTheDocument();
  });

  it("renders the chart container when financials are present", () => {
    render(<RevenueProfitChart financials={SAMPLE_FINANCIALS} />);
    expect(screen.getByTestId("revenue-profit-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when financials are empty", () => {
    render(<RevenueProfitChart financials={[]} />);
    expect(
      screen.getByText("Revenue and profit trend data was not available for this analysis."),
    ).toBeInTheDocument();
  });
});
