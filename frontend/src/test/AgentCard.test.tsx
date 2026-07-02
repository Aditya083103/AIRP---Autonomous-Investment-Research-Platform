// frontend/src/test/AgentCard.test.tsx
// Tests for AgentCard (T-059): each state renders its label and the
// right body content -- typing indicator for "thinking", the output
// preview for "complete"/"failed", and plain copy for "waiting"/"skipped".

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentCard } from "@/components/progress/AgentCard";
import { type AgentCardViewModel } from "@/lib/agentProgress";

function makeAgent(overrides: Partial<AgentCardViewModel> = {}): AgentCardViewModel {
  return {
    nodeName: "fundamental_analyst",
    displayName: "Fundamental Analyst",
    seat: 1,
    round: 1,
    state: "waiting",
    outputPreview: null,
    ...overrides,
  };
}

describe("AgentCard", () => {
  it("shows 'Waiting' and no output for a waiting agent", () => {
    render(<AgentCard agent={makeAgent({ state: "waiting" })} />);
    expect(screen.getByText("Waiting")).toBeInTheDocument();
    expect(screen.getByText("Waiting for its turn.")).toBeInTheDocument();
  });

  it("shows a typing indicator for a thinking agent", () => {
    render(<AgentCard agent={makeAgent({ state: "thinking" })} />);
    expect(screen.getByText("Thinking")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Thinking" })).toBeInTheDocument();
  });

  it("shows the output preview for a complete agent", () => {
    render(
      <AgentCard agent={makeAgent({ state: "complete", outputPreview: "Revenue grew 8% YoY." })} />,
    );
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Revenue grew 8% YoY.")).toBeInTheDocument();
  });

  it("shows the output preview for a failed agent too", () => {
    render(
      <AgentCard agent={makeAgent({ state: "failed", outputPreview: "yFinance timed out." })} />,
    );
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("yFinance timed out.")).toBeInTheDocument();
  });

  it("shows 'Skipped' copy for a skipped agent", () => {
    render(<AgentCard agent={makeAgent({ state: "skipped" })} />);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("Did not run for this analysis.")).toBeInTheDocument();
  });

  it("renders the agent's seat and display name", () => {
    render(<AgentCard agent={makeAgent({ seat: 5, displayName: "Risk Officer" })} />);
    expect(screen.getByText("Seat 5")).toBeInTheDocument();
    expect(screen.getByText("Risk Officer")).toBeInTheDocument();
  });
});
