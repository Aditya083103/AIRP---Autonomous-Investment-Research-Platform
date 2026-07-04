// frontend/src/test/AgentWeightsPanel.test.tsx
// Tests for AgentWeightsPanel (T-061): roster display names, weight ->
// percentage conversion, descending sort, unknown-key fallback, and
// the empty-weights case.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentWeightsPanel } from "@/components/results/AgentWeightsPanel";

describe("AgentWeightsPanel", () => {
  it("renders the committee roster display name for a known agent_name key", () => {
    render(<AgentWeightsPanel agentWeights={{ fundamental_analyst: 0.4 }} />);
    expect(screen.getByText("Fundamental Analyst")).toBeInTheDocument();
  });

  it("converts a 0.0-1.0 weight into a rounded percentage", () => {
    render(<AgentWeightsPanel agentWeights={{ valuation_agent: 0.256 }} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "26");
  });

  it("sorts agents by descending weight", () => {
    render(
      <AgentWeightsPanel
        agentWeights={{ contrarian_investor: 0.1, portfolio_manager: 0.5, risk_officer: 0.2 }}
      />,
    );
    const labels = screen.getAllByRole("progressbar").map((el) => el.getAttribute("aria-label"));
    expect(labels).toEqual(["Portfolio Manager", "Risk Officer", "Contrarian Investor"]);
  });

  it("falls back to a title-cased name for an agent_name not on the roster", () => {
    render(<AgentWeightsPanel agentWeights={{ unknown_future_agent: 0.5 }} />);
    expect(screen.getByText("Unknown Future Agent")).toBeInTheDocument();
  });

  it("shows a fallback message when there is no weighting data", () => {
    render(<AgentWeightsPanel agentWeights={{}} />);
    expect(screen.getByText("No agent weighting data was recorded.")).toBeInTheDocument();
  });
});
