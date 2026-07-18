// frontend/src/test/VerdictPanel.test.tsx
// Tests for VerdictPanel (T-061). Takes a full InvestmentDecisionResponse
// as a plain prop, so no API/query mocking is required here -- that is
// covered separately by useAnalysisResult.test.ts and
// AnalysisResultPage.test.tsx.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerdictPanel } from "@/components/results/VerdictPanel";
import { type InvestmentDecisionResponse } from "@/types/analysis";

function makeDecision(
  overrides: Partial<InvestmentDecisionResponse> = {},
): InvestmentDecisionResponse {
  return {
    agent_name: "portfolio_manager",
    analysis_id: "11111111-1111-1111-1111-111111111111",
    company_name: "Tata Consultancy Services",
    ticker: "TCS.NS",
    generated_at: "2026-06-15T10:30:00Z",
    error: null,
    verdict: "BUY",
    conviction_score: 8,
    price_target: "₹4,200 (12-month)",
    time_horizon: "12 months",
    executive_summary: "TCS shows resilient revenue growth and strong cash generation.",
    investment_thesis: "Margin expansion and digital demand support a BUY.",
    bull_case: "Revenue growth accelerating with strong deal wins.",
    bear_case: "Valuation is rich relative to historical average.",
    risk_summary: "Client concentration and currency headwinds are the top risks.",
    valuation_summary: "DCF implies 15% upside to the current price.",
    key_risks: ["Client concentration in BFSI", "INR/USD volatility"],
    key_catalysts: ["Large deal pipeline", "Margin recovery"],
    contrarian_response: "The Contrarian's margin concern is addressed by Q4 guidance.",
    debate_rounds_used: 2,
    agent_weights: { fundamental_analyst: 0.3, valuation_agent: 0.25 },
    summary: "TCS: BUY with conviction 8/10 -- strong fundamentals, reasonable valuation.",
    fundamental_years_available: null,
    ...overrides,
  };
}

describe("VerdictPanel", () => {
  it("renders the BUY verdict badge", () => {
    render(<VerdictPanel decision={makeDecision({ verdict: "BUY" })} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("renders the HOLD verdict badge", () => {
    render(<VerdictPanel decision={makeDecision({ verdict: "HOLD" })} />);
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });

  it("renders the SELL verdict badge", () => {
    render(<VerdictPanel decision={makeDecision({ verdict: "SELL" })} />);
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });

  it("renders the conviction gauge with the decision's score", () => {
    render(<VerdictPanel decision={makeDecision({ conviction_score: 9, verdict: "BUY" })} />);
    expect(screen.getByRole("img", { name: "Conviction score 9 out of 10" })).toBeInTheDocument();
  });

  it("renders the price target", () => {
    render(<VerdictPanel decision={makeDecision({ price_target: "₹4,200 (12-month)" })} />);
    expect(screen.getByText("₹4,200 (12-month)")).toBeInTheDocument();
  });

  it("shows 'Not determined' when price_target is null", () => {
    render(<VerdictPanel decision={makeDecision({ price_target: null })} />);
    expect(screen.getByText("Not determined")).toBeInTheDocument();
  });

  it("renders the time horizon", () => {
    render(<VerdictPanel decision={makeDecision({ time_horizon: "3-6 months" })} />);
    expect(screen.getByText("3-6 months")).toBeInTheDocument();
  });

  it("renders the one-sentence dashboard summary", () => {
    render(<VerdictPanel decision={makeDecision({ summary: "A concise verdict summary." })} />);
    expect(screen.getByText("A concise verdict summary.")).toBeInTheDocument();
  });
});
