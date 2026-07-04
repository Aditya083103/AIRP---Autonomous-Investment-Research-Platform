// frontend/src/test/RiskRadarChart.test.tsx
// Tests for RiskRadarChart (T-062). See StockPriceChart.test.tsx's
// docstring for the jsdom/Recharts testing approach.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskRadarChart } from "@/components/charts/RiskRadarChart";
import { type RiskRadarResponse } from "@/types/analysis";

const SAMPLE_RISK: RiskRadarResponse = {
  risk_score: 4,
  governance_risk: 3,
  regulatory_risk: 2,
  financial_risk: 5,
  concentration_risk: 6,
};

describe("RiskRadarChart", () => {
  it("renders the chart title", () => {
    render(<RiskRadarChart risk={SAMPLE_RISK} />);
    expect(screen.getByText("Risk profile")).toBeInTheDocument();
  });

  it("renders the chart container when risk data is present", () => {
    render(<RiskRadarChart risk={SAMPLE_RISK} />);
    expect(screen.getByTestId("risk-radar-chart")).toBeInTheDocument();
  });

  it("shows a fallback message when risk is null", () => {
    render(<RiskRadarChart risk={null} />);
    expect(screen.getByText("Risk data was not available for this analysis.")).toBeInTheDocument();
  });
});
