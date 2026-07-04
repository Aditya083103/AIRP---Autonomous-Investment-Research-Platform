// frontend/src/test/debateTranscript.test.ts
// Tests for debateTranscript.ts (T-060). Pure-function fixtures only --
// mirrors the style agentProgress.test.ts already established for the
// sibling module this one is derived from.

import { describe, expect, it } from "vitest";

import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import {
  buildDebateTranscript,
  DEBATE_ROUND_LABELS,
  messagesForRound,
} from "@/lib/debateTranscript";

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

describe("buildDebateTranscript", () => {
  it("returns an empty transcript for an empty event stream", () => {
    expect(buildDebateTranscript([])).toEqual([]);
  });

  it("maps a committee agent's event to a message with roster metadata", () => {
    const [message] = buildDebateTranscript([
      makeEvent({ agent: "fundamental_analyst", output_preview: "Margins expanded." }),
    ]);

    expect(message).toMatchObject({
      nodeName: "fundamental_analyst",
      displayName: "Fundamental Analyst",
      seat: 1,
      round: 1,
      status: "completed",
      content: "Margins expanded.",
      turn: 1,
    });
  });

  it("skips non-committee pipeline nodes such as the planner", () => {
    const messages = buildDebateTranscript([
      makeEvent({ agent: "planner" }),
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "research_join" }),
      makeEvent({ agent: "pdf_export" }),
    ]);

    expect(messages).toHaveLength(1);
    expect(messages[0]?.nodeName).toBe("fundamental_analyst");
  });

  it("preserves arrival order and assigns increasing turn numbers", () => {
    const messages = buildDebateTranscript([
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "technical_analyst" }),
      makeEvent({ agent: "sentiment_analyst" }),
    ]);

    expect(messages.map((message) => message.nodeName)).toEqual([
      "fundamental_analyst",
      "technical_analyst",
      "sentiment_analyst",
    ]);
    expect(messages.map((message) => message.turn)).toEqual([1, 2, 3]);
  });

  it("keeps every occurrence when an agent speaks more than once in the debate loop", () => {
    const messages = buildDebateTranscript([
      makeEvent({ agent: "contrarian_investor", output_preview: "First challenge." }),
      makeEvent({ agent: "risk_officer", output_preview: "Flagging concentration risk." }),
      makeEvent({ agent: "contrarian_investor", output_preview: "Second-round rebuttal." }),
    ]);

    const contrarianMessages = messages.filter(
      (message) => message.nodeName === "contrarian_investor",
    );
    expect(contrarianMessages).toHaveLength(2);
    expect(contrarianMessages.map((message) => message.content)).toEqual([
      "First challenge.",
      "Second-round rebuttal.",
    ]);
    expect(contrarianMessages[0]?.id).not.toBe(contrarianMessages[1]?.id);
  });
});

describe("messagesForRound", () => {
  it("filters messages down to the requested round only", () => {
    const messages = buildDebateTranscript([
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "risk_officer" }),
      makeEvent({ agent: "portfolio_manager" }),
    ]);

    expect(messagesForRound(messages, 1).map((message) => message.nodeName)).toEqual([
      "fundamental_analyst",
    ]);
    expect(messagesForRound(messages, 2).map((message) => message.nodeName)).toEqual([
      "risk_officer",
    ]);
    expect(messagesForRound(messages, 3).map((message) => message.nodeName)).toEqual([
      "portfolio_manager",
    ]);
  });

  it("returns an empty array for a round with no messages yet", () => {
    const messages = buildDebateTranscript([makeEvent({ agent: "fundamental_analyst" })]);
    expect(messagesForRound(messages, 3)).toEqual([]);
  });
});

describe("buildDebateTranscript status derivation (bugfix)", () => {
  it("shows 'completed' for a past turn even when the wire status is still 'running'", () => {
    // Regression test: backend/graph/nodes.py's _run_broadcast sets each
    // event's `status` field from the overall pipeline's InvestmentState
    // status, which stays "running" for virtually the whole analysis --
    // only the very last event ever carries "completed". Before this
    // fix, every past turn's badge showed "running" even though that
    // agent had clearly already finished speaking.
    const [message] = buildDebateTranscript([
      makeEvent({
        agent: "fundamental_analyst",
        status: "running",
        output_preview: "Fundamental score 7/10",
      }),
    ]);

    expect(message?.status).toBe("completed");
  });

  it("shows 'failed' when this agent's own output_preview is prefixed 'Failed:'", () => {
    const [message] = buildDebateTranscript([
      makeEvent({
        agent: "technical_analyst",
        status: "running",
        output_preview: "Failed: yfinance rate limited",
      }),
    ]);

    expect(message?.status).toBe("failed");
  });

  it("does not mistake 'failed' appearing mid-sentence for the Failed: prefix", () => {
    const [message] = buildDebateTranscript([
      makeEvent({
        agent: "risk_officer",
        output_preview: "Risk score 4/10 -- 2 flag(s) raised, none failed audits",
      }),
    ]);

    expect(message?.status).toBe("completed");
  });
});

describe("DEBATE_ROUND_LABELS", () => {
  it("provides a label for all three rounds", () => {
    expect(DEBATE_ROUND_LABELS[1]).toMatch(/research/i);
    expect(DEBATE_ROUND_LABELS[2]).toMatch(/debate/i);
    expect(DEBATE_ROUND_LABELS[3]).toMatch(/decision/i);
  });
});
