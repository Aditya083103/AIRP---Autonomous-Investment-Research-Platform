// frontend/src/test/DebateViewer.test.tsx
// Tests for DebateViewer (T-060). Takes events as a plain prop (like
// AgentProgressBoard.tsx), so no WebSocket mocking is required -- just
// hand-built AgentStreamEvent fixtures.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DebateViewer } from "@/components/debate/DebateViewer";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";

function makeEvent(overrides: Partial<AgentStreamEvent> & { agent: string }): AgentStreamEvent {
  return {
    job_id: "job-1",
    status: "completed",
    output_preview: `${overrides.agent} output`,
    progress_percent: 0,
    is_final: false,
    ...overrides,
  };
}

describe("DebateViewer", () => {
  it("renders all three round headings even with no events yet", () => {
    render(<DebateViewer events={[]} />);

    expect(screen.getByText(/round 1.*research findings/i)).toBeInTheDocument();
    expect(screen.getByText(/round 2.*debate/i)).toBeInTheDocument();
    expect(screen.getByText(/round 3.*final decision/i)).toBeInTheDocument();
  });

  it("shows an empty-state note before any agent has spoken", () => {
    render(<DebateViewer events={[]} />);
    expect(
      screen.getByText(/debate transcript will appear here once the committee starts speaking/i),
    ).toBeInTheDocument();
  });

  it("places each message under its own round", () => {
    render(
      <DebateViewer
        events={[
          makeEvent({ agent: "fundamental_analyst", output_preview: "Margins expanded." }),
          makeEvent({ agent: "risk_officer", output_preview: "Concentration risk flagged." }),
          makeEvent({ agent: "portfolio_manager", output_preview: "BUY, conviction 8." }),
        ]}
      />,
    );

    expect(screen.getByText("Margins expanded.")).toBeInTheDocument();
    expect(screen.getByText("Concentration risk flagged.")).toBeInTheDocument();
    expect(screen.getByText("BUY, conviction 8.")).toBeInTheDocument();
    // No round shows the "no messages yet" placeholder once every round has content.
    expect(screen.queryByText("No messages yet in this round.")).not.toBeInTheDocument();
  });

  it("shows a per-round placeholder only for rounds with no messages yet", () => {
    render(<DebateViewer events={[makeEvent({ agent: "fundamental_analyst" })]} />);

    // Round 1 has a message, rounds 2 and 3 don't yet.
    expect(screen.getAllByText("No messages yet in this round.")).toHaveLength(2);
  });

  it("renders every message in a debate loop, not just the latest per agent", () => {
    render(
      <DebateViewer
        events={[
          makeEvent({ agent: "contrarian_investor", output_preview: "First challenge." }),
          makeEvent({ agent: "contrarian_investor", output_preview: "Second rebuttal." }),
        ]}
      />,
    );

    expect(screen.getByText("First challenge.")).toBeInTheDocument();
    expect(screen.getByText("Second rebuttal.")).toBeInTheDocument();
  });

  it("ignores non-committee pipeline events such as the planner", () => {
    render(
      <DebateViewer
        events={[makeEvent({ agent: "planner", output_preview: "Resolving ticker." })]}
      />,
    );

    expect(screen.queryByText("Resolving ticker.")).not.toBeInTheDocument();
    expect(screen.getAllByText("No messages yet in this round.")).toHaveLength(3);
  });
});
