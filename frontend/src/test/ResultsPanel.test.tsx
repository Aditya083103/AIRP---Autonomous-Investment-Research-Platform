// frontend/src/test/ResultsPanel.test.tsx
// Tests for ResultsPanel (T-061) -- the top-level composition of every
// InvestmentDecisionResponse field. Each child panel already has its
// own focused test file (VerdictPanel.test.tsx, BullBearPanel.test.tsx,
// KeyRisksList.test.tsx, MemoSection.test.tsx, AgentWeightsPanel.test.tsx);
// this file's job is to confirm every field actually reaches the page
// once wired together, not to re-test each child's internal behaviour.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultsPanel } from "@/components/results/ResultsPanel";
import { type InvestmentDecisionResponse } from "@/types/analysis";

function makeDecision(
  overrides: Partial<InvestmentDecisionResponse> = {},
): InvestmentDecisionResponse {
  return {
    agent_name: "portfolio_manager",
    analysis_id: "11111111-1111-1111-1111-111111111111",
    company_name: "Tata Consultancy Services",
    ticker: "TCS.NS",
    generated_at: "2026-06-15T10:30:00.000Z",
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

describe("ResultsPanel", () => {
  it("renders the verdict panel", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(screen.getByTestId("verdict-panel")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
  });

  it("renders the executive summary and investment thesis", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(
      screen.getByText("TCS shows resilient revenue growth and strong cash generation."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Margin expansion and digital demand support a BUY."),
    ).toBeInTheDocument();
  });

  it("renders the bull/bear panel", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(screen.getByTestId("bull-bear-panel")).toBeInTheDocument();
  });

  it("renders the key risks and catalysts panel", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(screen.getByTestId("key-risks-list")).toBeInTheDocument();
  });

  it("renders the valuation summary", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(screen.getByText("DCF implies 15% upside to the current price.")).toBeInTheDocument();
  });

  it("renders the contrarian resolution with the debate round count", () => {
    render(<ResultsPanel decision={makeDecision({ debate_rounds_used: 2 })} />);
    expect(screen.getByText("Contrarian resolution (2 debate rounds)")).toBeInTheDocument();
    expect(
      screen.getByText("The Contrarian's margin concern is addressed by Q4 guidance."),
    ).toBeInTheDocument();
  });

  it("uses singular 'round' when only one debate round occurred", () => {
    render(<ResultsPanel decision={makeDecision({ debate_rounds_used: 1 })} />);
    expect(screen.getByText("Contrarian resolution (1 debate round)")).toBeInTheDocument();
  });

  it("renders the agent weights panel", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    expect(screen.getByTestId("agent-weights-panel")).toBeInTheDocument();
  });

  it("renders the company name, ticker, and generated-at meta line", () => {
    render(<ResultsPanel decision={makeDecision()} />);
    const meta = screen.getByTestId("results-panel-meta");
    expect(meta).toHaveTextContent("Tata Consultancy Services");
    expect(meta).toHaveTextContent("TCS.NS");
  });
});
