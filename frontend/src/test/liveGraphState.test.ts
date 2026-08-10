// frontend/src/test/liveGraphState.test.ts
// Tests for src/lib/graph/liveGraphState.ts (T-096; T-097 adds the
// deriveDebateLoopEdgeState section at the bottom). Pure data
// assertions only -- no rendering -- matching
// src/test/pipelineTopology.test.ts and src/test/agentProgress.test.ts's
// own established "given identical inputs, always the same output"
// testing style for this codebase's pure derivation modules.

import { describe, expect, it } from "vitest";

import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import { deriveDebateLoopEdgeState, deriveNodeStatuses } from "@/lib/graph/liveGraphState";
import {
  NODE_CONTRARIAN,
  NODE_DEBATE_LOOP,
  NODE_END,
  NODE_FUNDAMENTAL,
  NODE_MACRO,
  NODE_PDF_EXPORT,
  NODE_PLANNER,
  NODE_RESEARCH_JOIN,
  NODE_RISK,
  NODE_SENTIMENT,
  NODE_START,
  NODE_TECHNICAL,
} from "@/lib/graph/pipelineTopology";

function makeEvent(overrides: Partial<AgentStreamEvent>): AgentStreamEvent {
  return {
    job_id: "job-1",
    agent: NODE_PLANNER,
    status: "running",
    output_preview: "",
    progress_percent: 0,
    is_final: false,
    event_type: "node_completed",
    ...overrides,
  };
}

describe("deriveNodeStatuses", () => {
  it("marks every real node pending, and START pending, when no events have arrived", () => {
    const statuses = deriveNodeStatuses([], false);
    expect(statuses[NODE_PLANNER]).toBe("pending");
    expect(statuses[NODE_FUNDAMENTAL]).toBe("pending");
    expect(statuses[NODE_START]).toBe("pending");
    expect(statuses[NODE_END]).toBe("pending");
  });

  it("marks START done the instant any event has arrived", () => {
    const events = [makeEvent({ agent: NODE_PLANNER, event_type: "node_started" })];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_START]).toBe("done");
  });

  it("marks a node running when its own latest event is a started event", () => {
    const events = [makeEvent({ agent: NODE_PLANNER, event_type: "node_started" })];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_PLANNER]).toBe("running");
  });

  it("marks a node done once its own latest event is a completed event", () => {
    const events = [
      makeEvent({ agent: NODE_PLANNER, event_type: "node_started" }),
      makeEvent({ agent: NODE_PLANNER, event_type: "node_completed", status: "running" }),
    ];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_PLANNER]).toBe("done");
  });

  it("marks a node failed when its latest completed event's status is 'failed'", () => {
    const events = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_completed", status: "failed" }),
    ];
    const statuses = deriveNodeStatuses(events, true);
    expect(statuses[NODE_FUNDAMENTAL]).toBe("failed");
  });

  it("uses only the MOST RECENT event for a node, not the first", () => {
    // debate_loop / contrarian_investor can legitimately run more than
    // once (T-040's debate loop cycle) -- the node's status must always
    // reflect its newest event, not go stale on an earlier round.
    const events = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }), // round 2
    ];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_CONTRARIAN]).toBe("running");
    expect(statuses[NODE_DEBATE_LOOP]).toBe("done");
  });

  it("treats a missing event_type as a completed event, never as running", () => {
    // Mirrors backend.services.ws_broadcaster.cast_event's own default
    // (event_type defaults to "node_completed") -- an event that
    // predates T-095, or a hand-built fixture with no event_type field
    // at all, must never leave a node stuck mid-pulse.
    const { event_type: _omit, ...eventWithoutType } = makeEvent({ agent: NODE_RISK });
    const statuses = deriveNodeStatuses([eventWithoutType as AgentStreamEvent], false);
    expect(statuses[NODE_RISK]).toBe("done");
  });

  it("animates the 4 parallel research nodes simultaneously (each independently 'running')", () => {
    // T-096's second acceptance criterion. The 4 research nodes'
    // started events arrive close together (they run in the same
    // LangGraph Send super-step) but this module needs no special-case
    // code for that -- each node's own latest event drives its own
    // status, so 4 concurrent started events simply produce 4
    // concurrent "running" statuses.
    const events = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_started" }),
    ];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_FUNDAMENTAL]).toBe("running");
    expect(statuses[NODE_TECHNICAL]).toBe("running");
    expect(statuses[NODE_SENTIMENT]).toBe("running");
    expect(statuses[NODE_MACRO]).toBe("running");
  });

  it("lets 3 of 4 parallel nodes finish while the 4th is still running", () => {
    const events = [
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_started" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_started" }),
      makeEvent({ agent: NODE_MACRO, event_type: "node_started" }),
      makeEvent({ agent: NODE_FUNDAMENTAL, event_type: "node_completed" }),
      makeEvent({ agent: NODE_TECHNICAL, event_type: "node_completed" }),
      makeEvent({ agent: NODE_SENTIMENT, event_type: "node_completed" }),
    ];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_FUNDAMENTAL]).toBe("done");
    expect(statuses[NODE_TECHNICAL]).toBe("done");
    expect(statuses[NODE_SENTIMENT]).toBe("done");
    expect(statuses[NODE_MACRO]).toBe("running");
  });

  it("leaves a node never touched this run pending, even once the pipeline completes", () => {
    // A conditional branch node (error_handler, sentiment_escalation)
    // that this particular run never took should stay visually neutral
    // -- "pending" forever, not "skipped" -- since never running is the
    // expected, correct outcome for a branch not taken, not an anomaly.
    const events = [
      makeEvent({ agent: NODE_PLANNER, event_type: "node_started" }),
      makeEvent({ agent: NODE_PLANNER, event_type: "node_completed" }),
    ];
    const statuses = deriveNodeStatuses(events, true);
    expect(statuses["error_handler"]).toBe("pending");
  });

  it("marks END pending while the stream is still open, even with many events in", () => {
    const events = [
      makeEvent({ agent: NODE_PLANNER, event_type: "node_started" }),
      makeEvent({ agent: NODE_PLANNER, event_type: "node_completed" }),
      makeEvent({ agent: NODE_RESEARCH_JOIN, event_type: "node_started" }),
    ];
    const statuses = deriveNodeStatuses(events, false);
    expect(statuses[NODE_END]).toBe("pending");
  });

  it("marks END done once isComplete is true and the run succeeded", () => {
    const events = [
      makeEvent({ agent: NODE_PDF_EXPORT, event_type: "node_completed", is_final: true }),
    ];
    const statuses = deriveNodeStatuses(events, true);
    expect(statuses[NODE_END]).toBe("done");
  });

  it("marks END failed once isComplete is true and the run's last event failed", () => {
    const events = [
      makeEvent({
        agent: NODE_FUNDAMENTAL,
        event_type: "node_completed",
        status: "failed",
        is_final: true,
      }),
    ];
    const statuses = deriveNodeStatuses(events, true);
    expect(statuses[NODE_END]).toBe("failed");
  });
});

describe("deriveDebateLoopEdgeState", () => {
  it("is inactive with no current round before the debate has started", () => {
    const state = deriveDebateLoopEdgeState([], deriveNodeStatuses([], false));
    expect(state.active).toBe(false);
    expect(state.currentRound).toBeNull();
  });

  it("activates the instant contrarian_investor starts round 1", () => {
    const events = [makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" })];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    expect(state.active).toBe(true);
    expect(state.currentRound).toBe(1);
  });

  it("stays active while debate_loop itself is running, after contrarian completes", () => {
    const events = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
    ];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    expect(state.active).toBe(true);
    expect(state.currentRound).toBe(1);
  });

  it("goes inactive in the gap after round 1 completes, before round 2 starts", () => {
    const events = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
    ];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    expect(state.active).toBe(false);
    // Round 1 already fully ran (contrarian started once) -- still
    // reported as round 1 until round 2's contrarian event arrives.
    expect(state.currentRound).toBe(1);
  });

  it("reactivates for round 2 once contrarian_investor starts again", () => {
    const events = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }), // round 2
    ];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    expect(state.active).toBe(true);
    expect(state.currentRound).toBe(2);
  });

  it("goes inactive for good once round 2's debate_loop completes", () => {
    const events = [
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }),
      makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }),
      makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }),
      makeEvent({ agent: NODE_RISK, event_type: "node_started" }),
    ];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    expect(state.active).toBe(false);
    expect(state.currentRound).toBe(2);
  });

  it("produces a genuine active/inactive/active/inactive cycle across both rounds", () => {
    // The literal "round-trip pulse... across its 2 rounds" acceptance
    // criterion, checked as a single ordered sequence of active flags
    // rather than four separate tests, so a regression that merges two
    // of these phases together (e.g. staying active straight through
    // both rounds with no gap) fails this one test directly.
    const timeline: { events: AgentStreamEvent[]; expectedActive: boolean }[] = [];
    const events: AgentStreamEvent[] = [];

    function record(expectedActive: boolean): void {
      timeline.push({ events: [...events], expectedActive });
    }

    events.push(makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }));
    record(true); // round 1 begins

    events.push(makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }));
    record(true); // still round 1

    events.push(makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }));
    record(false); // gap between rounds

    events.push(makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_started" }));
    record(true); // round 2 begins

    events.push(makeEvent({ agent: NODE_CONTRARIAN, event_type: "node_completed" }));
    events.push(makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_started" }));
    record(true); // still round 2

    events.push(makeEvent({ agent: NODE_DEBATE_LOOP, event_type: "node_completed" }));
    record(false); // debate concluded for good

    for (const { events: snapshot, expectedActive } of timeline) {
      const state = deriveDebateLoopEdgeState(snapshot, deriveNodeStatuses(snapshot, false));
      expect(state.active).toBe(expectedActive);
    }
  });

  it("treats a missing event_type on a contrarian event as not-started", () => {
    const { event_type: _omit, ...eventWithoutType } = makeEvent({ agent: NODE_CONTRARIAN });
    const events = [eventWithoutType as AgentStreamEvent];
    const state = deriveDebateLoopEdgeState(events, deriveNodeStatuses(events, false));
    // A completed-shaped (missing event_type) contrarian event should
    // not itself be counted as a "round started" -- only a genuine
    // node_started event advances the round counter.
    expect(state.currentRound).toBeNull();
    expect(state.active).toBe(false);
  });
});
