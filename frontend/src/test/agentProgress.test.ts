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

  // -------------------------------------------------------------------
  // B3: a live connection can miss an individual round-1 research
  // agent's own events (a Send-parallel branch that fired before this
  // connection subscribed). research_join cannot complete unless all 4
  // round-1 agents already have, so its arrival is authoritative proof
  // those seats ran -- mirroring backend/routers/websocket.py's own
  // `_snapshot_to_events` expansion of research_join into its 4
  // upstream agents on a fresh reconnect/reload.
  // -------------------------------------------------------------------

  it("marks a round-1 seat complete via research_join even with no event of its own", () => {
    const events = [
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "technical_analyst" }),
      makeEvent({ agent: "sentiment_analyst" }),
      // macro_economist's own event never arrived on this connection.
      makeEvent({ agent: "research_join", output_preview: "Research complete." }),
    ];
    const cards = deriveAgentCards(events, false);
    const macro = cards.find((card) => card.nodeName === "macro_economist");
    expect(macro?.state).toBe("complete");
    expect(macro?.outputPreview).toBe("Research complete.");
  });

  it("does not mark a missing round-1 seat as skipped once the job terminates, when research_join fired", () => {
    const events = [
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "technical_analyst" }),
      makeEvent({ agent: "sentiment_analyst" }),
      makeEvent({ agent: "research_join" }),
    ];
    // The exact bug this fix targets: isComplete=true (job terminated)
    // must not flip macro_economist to "skipped" just because this
    // live connection never received its own event.
    const cards = deriveAgentCards(events, true);
    const macro = cards.find((card) => card.nodeName === "macro_economist");
    expect(macro?.state).toBe("complete");
  });

  it("marks a missing round-1 seat failed (not complete) if research_join itself reports failed", () => {
    const events = [makeEvent({ agent: "research_join", status: "failed" })];
    const cards = deriveAgentCards(events, false);
    const fundamental = cards.find((card) => card.nodeName === "fundamental_analyst");
    expect(fundamental?.state).toBe("failed");
  });

  it("a seat's own event always takes priority over the research_join fallback", () => {
    const events = [
      makeEvent({
        agent: "fundamental_analyst",
        status: "failed",
        output_preview: "Rate limited.",
      }),
      makeEvent({ agent: "research_join", output_preview: "Research complete." }),
    ];
    const cards = deriveAgentCards(events, false);
    const fundamental = cards.find((card) => card.nodeName === "fundamental_analyst");
    expect(fundamental?.state).toBe("failed");
    expect(fundamental?.outputPreview).toBe("Rate limited.");
  });

  it("research_join does not affect round-2/round-3 seats directly (only promotes them via roundIsComplete)", () => {
    const events = [makeEvent({ agent: "research_join" })];
    const cards = deriveAgentCards(events, false);
    const riskOfficer = cards.find((card) => card.nodeName === "risk_officer");
    // Round 1 is done (via research_join), so Round 2 is now "thinking",
    // not "complete" -- research_join is not itself risk_officer's event.
    expect(riskOfficer?.state).toBe("thinking");
  });

  it("promotes Round 2 to thinking via research_join even when a round-1 seat's own event never arrived", () => {
    const events = [
      makeEvent({ agent: "fundamental_analyst" }),
      makeEvent({ agent: "technical_analyst" }),
      makeEvent({ agent: "sentiment_analyst" }),
      // macro_economist's own event missing, but research_join fired.
      makeEvent({ agent: "research_join" }),
    ];
    const cards = deriveAgentCards(events, false);
    const riskOfficer = cards.find((card) => card.nodeName === "risk_officer");
    expect(riskOfficer?.state).toBe("thinking");
  });

  it("without research_join, a missing round-1 seat still renders skipped once terminated (no over-eager synthesis)", () => {
    const events = [makeEvent({ agent: "fundamental_analyst" })];
    const cards = deriveAgentCards(events, true);
    const technical = cards.find((card) => card.nodeName === "technical_analyst");
    expect(technical?.state).toBe("skipped");
  });

  // -------------------------------------------------------------------
  // General downstream-evidence reconciliation (hasLaterPipelineEvidence):
  // the exact bug reported live -- "Risk Officer / Contrarian Investor /
  // Valuation Agent / Portfolio Manager show 'Did not run for this
  // analysis' even though the completed Investment Memo clearly
  // included all of their output". A live connection can miss ANY
  // single node's own event, not just a round-1 research agent's --
  // an event for a LATER node in the sequential pipeline
  // (research_join -> contrarian_investor -> debate_loop ->
  // risk_officer -> valuation_agent -> portfolio_manager ->
  // report_generator -> pdf_export) is authoritative proof every
  // earlier node in that sequence also ran.
  // -------------------------------------------------------------------

  it("marks contrarian_investor and risk_officer complete via a later valuation_agent event, with no events of their own", () => {
    const events = [makeEvent({ agent: "valuation_agent" })];
    const cards = deriveAgentCards(events, false);
    const contrarian = cards.find((card) => card.nodeName === "contrarian_investor");
    const risk = cards.find((card) => card.nodeName === "risk_officer");
    expect(contrarian?.state).toBe("complete");
    expect(risk?.state).toBe("complete");
  });

  it("does not mark risk_officer/contrarian/valuation as skipped once terminated when only portfolio_manager's event arrived", () => {
    const events = [makeEvent({ agent: "portfolio_manager" })];
    const cards = deriveAgentCards(events, true);
    const contrarian = cards.find((card) => card.nodeName === "contrarian_investor");
    const risk = cards.find((card) => card.nodeName === "risk_officer");
    const valuation = cards.find((card) => card.nodeName === "valuation_agent");
    expect(contrarian?.state).toBe("complete");
    expect(risk?.state).toBe("complete");
    expect(valuation?.state).toBe("complete");
  });

  it("marks every round-1 agent complete via a downstream contrarian_investor event even when research_join's own event was also missed", () => {
    const events = [makeEvent({ agent: "contrarian_investor" })];
    const cards = deriveAgentCards(events, true);
    const round1 = cards.filter((card) => card.round === 1);
    expect(round1.every((card) => card.state === "complete")).toBe(true);
  });

  it("a seat's own event still takes priority over downstream-evidence reconciliation", () => {
    const events = [
      makeEvent({ agent: "risk_officer", status: "failed", output_preview: "LLM error." }),
      makeEvent({ agent: "valuation_agent" }),
    ];
    const cards = deriveAgentCards(events, false);
    const risk = cards.find((card) => card.nodeName === "risk_officer");
    expect(risk?.state).toBe("failed");
    expect(risk?.outputPreview).toBe("LLM error.");
  });

  it("does not synthesise completion for a seat with no later pipeline evidence at all", () => {
    const events = [makeEvent({ agent: "contrarian_investor" })];
    const cards = deriveAgentCards(events, true);
    const portfolioManager = cards.find((card) => card.nodeName === "portfolio_manager");
    // Nothing after portfolio_manager's own position ever fired, and it
    // has no event of its own -- genuinely skipped, not synthesised.
    expect(portfolioManager?.state).toBe("skipped");
  });
});
