// frontend/src/test/AgentProgressBoard.test.tsx
// Tests for AgentProgressBoard (T-059). Takes events/isComplete/etc as
// plain props (it does not call useAnalysisStream itself), so these
// tests need no WebSocket mocking at all -- just hand-built event
// arrays, the same fixtures agentProgress.test.ts already uses.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentProgressBoard } from "@/components/progress/AgentProgressBoard";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";

function makeEvent(overrides: Partial<AgentStreamEvent> & { agent: string }): AgentStreamEvent {
  return {
    job_id: "job-1",
    status: "running",
    output_preview: `${overrides.agent} output`,
    progress_percent: 0,
    is_final: false,
    ...overrides,
  };
}

describe("AgentProgressBoard", () => {
  it("renders all three round headings", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={0}
        connectionStatus="open"
        error={null}
      />,
    );
    expect(screen.getByText(/round 1.*parallel research/i)).toBeInTheDocument();
    expect(screen.getByText(/round 2.*debate/i)).toBeInTheDocument();
    expect(screen.getByText(/final call/i)).toBeInTheDocument();
  });

  it("renders all 8 committee agent cards", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={0}
        connectionStatus="open"
        error={null}
      />,
    );
    for (const name of [
      "Fundamental Analyst",
      "Technical Analyst",
      "News Sentiment Agent",
      "Macro Economist",
      "Risk Officer",
      "Contrarian Investor",
      "Valuation Agent",
      "Portfolio Manager",
    ]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("shows the overall progress percentage", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={42}
        connectionStatus="open"
        error={null}
      />,
    );
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("shows a connecting indicator while the socket is connecting", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={0}
        connectionStatus="connecting"
        error={null}
      />,
    );
    expect(screen.getByText("Connecting to the committee…")).toBeInTheDocument();
  });

  it("shows a live indicator once the socket is open and the job is running", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={10}
        connectionStatus="open"
        error={null}
      />,
    );
    expect(screen.getByText("Live — streaming agent updates")).toBeInTheDocument();
  });

  it("reflects a completed agent's output on its card", () => {
    render(
      <AgentProgressBoard
        events={[makeEvent({ agent: "fundamental_analyst", output_preview: "Margins expanded." })]}
        isComplete={false}
        progressPercent={20}
        connectionStatus="open"
        error={null}
      />,
    );
    expect(screen.getByText("Margins expanded.")).toBeInTheDocument();
  });

  it("shows a connection error banner when given one", () => {
    render(
      <AgentProgressBoard
        events={[]}
        isComplete={false}
        progressPercent={0}
        connectionStatus="error"
        error="WebSocket connection error."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("WebSocket connection error.");
  });
});
