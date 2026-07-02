// frontend/src/test/agentProgress.test.ts
// Tests for src/lib/agentProgress.ts (T-059). deriveAgentCards is pure,
// so these tests assert its output directly against hand-built event
// arrays -- no timers, no mocked sockets, no waiting. The
// "does not depend on arrival order within the same round" test is the
// direct check for the acceptance criterion's "no race conditions":
// since the four Round 1 agents run in parallel, they can complete in
// any order, and the derived board must be identical regardless of
// which order their events happened to arrive in.

import { describe, expect, it } from "vitest";

import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import { COMMITTEE_ROSTER, deriveAgentCards } from "@/lib/agentProgress";

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

describe("deriveAgentCards", () => {
  it("returns exactly one card per committee roster entry", () => {
    const cards = deriveAgentCards([], false);
    expect(cards).toHaveLength(COMMITTEE_ROSTER.length);
  });

  it("marks every Round 1 agent as thinking before any event arrives", () => {
    const cards = deriveAgentCards([], false);
    const round1 = cards.filter((card) => card.round === 1);
    expect(round1.every((card) => card.state === "thinking")).toBe(true);
  });

  it("marks every Round 2 and Round 3 agent as waiting before Round 1 finishes", () => {
    const cards = deriveAgentCards([], false);
    const laterRounds = cards.filter((card) => card.round !== 1);
    expect(laterRounds.every((card) => card.state === "waiting")).toBe(true);
  });

  it("marks an agent complete once its event arrives, with that event's output", () => {
    const events = [makeEvent({ agent: "fundamental_analyst", output_preview: "Strong margins." })];
    const cards = deriveAgentCards(events, false);
    const fundamental = cards.find((card) => card.nodeName === "fundamental_analyst");
    expect(fundamental?.state).toBe("complete");
    expect(fundamental?.outputPreview).toBe("Strong margins.");
  });

  it("marks an agent failed when its own event reports status 'failed'", () => {
    const events = [makeEvent({ agent: "fundamental_analyst", status: "failed" })];
    const cards = deriveAgentCards(events, false);
    const fundamental = cards.find((card) => card.nodeName === "fundamental_analyst");
    expect(fundamental?.state).toBe("failed");
  });

  it("promotes Round 2 to thinking only once every Round 1 agent has completed", () => {
    const threeOfFour = [
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "technical_analyst" }),
      makeEvent({ agent: "sentiment_analyst" }),
    ];
    const stillWaiting = deriveAgentCards(threeOfFour, false);
    const riskOfficer = stillWaiting.find((card) => card.nodeName === "risk_officer");
    expect(riskOfficer?.state).toBe("waiting");

    const allFour = [...threeOfFour, makeEvent({ agent: "macro_economist" })];
    const nowThinking = deriveAgentCards(allFour, false);
    const riskOfficerAfter = nowThinking.find((card) => card.nodeName === "risk_officer");
    expect(riskOfficerAfter?.state).toBe("thinking");
  });

  it("promotes the Portfolio Manager to thinking only once Rounds 1 and 2 both finish", () => {
    const round1And2Names = COMMITTEE_ROSTER.filter((entry) => entry.round < 3).map(
      (entry) => entry.nodeName,
    );
    const events = round1And2Names.map((agent) => makeEvent({ agent }));

    const cards = deriveAgentCards(events, false);
    const portfolioManager = cards.find((card) => card.nodeName === "portfolio_manager");
    expect(portfolioManager?.state).toBe("thinking");
  });

  it("does NOT depend on the arrival order of events within the same round", () => {
    const round1Names = COMMITTEE_ROSTER.filter((entry) => entry.round === 1).map(
      (entry) => entry.nodeName,
    );
    const forwardOrder = round1Names.map((agent) => makeEvent({ agent }));
    const reverseOrder = [...forwardOrder].reverse();

    const forwardResult = deriveAgentCards(forwardOrder, false);
    const reverseResult = deriveAgentCards(reverseOrder, false);

    // Compare by nodeName -> state rather than array order
    // (deriveAgentCards always returns cards in roster order
    // regardless of event order, which is itself part of the
    // no-race-conditions guarantee).
    const toStateMap = (cards: ReturnType<typeof deriveAgentCards>): Record<string, string> =>
      Object.fromEntries(cards.map((card) => [card.nodeName, card.state]));
    expect(toStateMap(forwardResult)).toEqual(toStateMap(reverseResult));
  });

  it("marks a not-yet-reached agent as skipped once the job has terminated", () => {
    const events = [makeEvent({ agent: "fundamental_analyst", status: "failed" })];
    const cards = deriveAgentCards(events, true);
    const technical = cards.find((card) => card.nodeName === "technical_analyst");
    expect(technical?.state).toBe("skipped");
  });

  it("does not mark a completed agent as skipped even after the job terminates", () => {
    const events = [makeEvent({ agent: "fundamental_analyst" })];
    const cards = deriveAgentCards(events, true);
    const fundamental = cards.find((card) => card.nodeName === "fundamental_analyst");
    expect(fundamental?.state).toBe("complete");
  });

  it("keeps a card complete (not reverting to thinking) when the same agent fires twice", () => {
    const events = [
      makeEvent({ agent: "risk_officer", output_preview: "First pass." }),
      makeEvent({ agent: "risk_officer", output_preview: "Second pass, revised." }),
    ];
    const cards = deriveAgentCards(events, false);
    const risk = cards.find((card) => card.nodeName === "risk_officer");
    expect(risk?.state).toBe("complete");
    expect(risk?.outputPreview).toBe("Second pass, revised.");
  });
});
