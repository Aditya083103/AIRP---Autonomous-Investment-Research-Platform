// frontend/src/lib/agentProgress.ts
// AIRP -- Agent progress derivation (T-059)
//
// Turns the raw AgentStreamEvent[] from useAnalysisStream.ts (T-049)
// into one view model per committee agent card. Deliberately a pure
// function with no React, no timers, and no subscription of its own --
// given the exact same `events` array and `isComplete` flag, it always
// returns the exact same result. That purity is what makes "no race
// conditions" (the T-059 acceptance criterion) checkable at all: a
// race condition would mean two different orderings of the same
// events produce different output, which is exactly what
// agentProgress.test.ts asserts against directly, with no timing,
// mocked sockets, or async waiting involved.
//
// Why "Thinking" has to be INFERRED, not read off the wire
// -----------------------------------------------------------
// backend.services.ws_broadcaster.AgentStreamEvent's own docstring is
// explicit: `agent` is "the LangGraph node name that just completed".
// There is no corresponding "node X has started" event -- the backend
// only ever announces completions. So a card can't be driven purely by
// "did agent X's event arrive yet"; it also needs to guess when an
// agent is *currently* running versus not yet reached. This module
// infers that from ROUND ORDER (mirroring the exact grouping
// src/components/landing/CommitteeSection.tsx already established in
// T-055 -- four research agents run in parallel, then three debate
// agents, then the Portfolio Manager): once every agent in every
// earlier round has a completion event, every not-yet-completed agent
// in the current round is shown as "thinking". This is an
// approximation, not a literal signal -- documented here so nobody
// mistakes "thinking" for "the backend told us this node started."

import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";

export type AgentCardState = "waiting" | "thinking" | "complete" | "failed" | "skipped";

export interface CommitteeRosterEntry {
  /** Exact LangGraph node name from backend.graph.nodes' NODE_* constants. */
  nodeName: string;
  displayName: string;
  seat: number;
  round: 1 | 2 | 3;
}

export interface AgentCardViewModel extends CommitteeRosterEntry {
  state: AgentCardState;
  /** Latest output_preview received for this agent, or null before its first event. */
  outputPreview: string | null;
}

/**
 * The 8 committee agents this viewer renders a card for, in the same
 * three execution rounds and seat numbers CommitteeSection.tsx (T-055)
 * already established. The raw event stream also carries a handful of
 * non-agent pipeline nodes (planner, research_join, error_handler,
 * sentiment_escalation, debate_loop, report_generator, pdf_export --
 * see backend/graph/nodes.py's NODE_* constants) -- this viewer
 * deliberately renders a card only for the 8 committee members the
 * task description and CommitteeSection both scope "agent" to, not
 * every graph node.
 */
export const COMMITTEE_ROSTER: readonly CommitteeRosterEntry[] = [
  { nodeName: "fundamental_analyst", displayName: "Fundamental Analyst", seat: 1, round: 1 },
  { nodeName: "technical_analyst", displayName: "Technical Analyst", seat: 2, round: 1 },
  { nodeName: "sentiment_analyst", displayName: "News Sentiment Agent", seat: 3, round: 1 },
  { nodeName: "macro_economist", displayName: "Macro Economist", seat: 4, round: 1 },
  { nodeName: "risk_officer", displayName: "Risk Officer", seat: 5, round: 2 },
  { nodeName: "contrarian_investor", displayName: "Contrarian Investor", seat: 6, round: 2 },
  { nodeName: "valuation_agent", displayName: "Valuation Agent", seat: 7, round: 2 },
  { nodeName: "portfolio_manager", displayName: "Portfolio Manager", seat: 8, round: 3 },
];

/**
 * The most recent event for `nodeName`, or undefined if none has
 * arrived yet. "Most recent" matters because a debate-loop agent
 * (Risk Officer, Contrarian Investor) can legitimately appear more
 * than once if the debate runs multiple rounds -- this viewer always
 * shows that card's newest output rather than its first, but does not
 * regress a card from "complete" back to "thinking" on a second event;
 * see this module's docstring for why round-tripping the debate loop
 * visually is out of scope.
 */
function latestEventFor(
  events: readonly AgentStreamEvent[],
  nodeName: string,
): AgentStreamEvent | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.agent === nodeName) {
      return events[index];
    }
  }
  return undefined;
}

function roundIsComplete(round: 1 | 2 | 3, events: readonly AgentStreamEvent[]): boolean {
  return COMMITTEE_ROSTER.filter((entry) => entry.round === round).every(
    (entry) => latestEventFor(events, entry.nodeName) !== undefined,
  );
}

/**
 * Derive one view model per COMMITTEE_ROSTER entry from the current
 * event stream. Safe to call on every render (or every new event) --
 * it never mutates its inputs and has no memory of its own between
 * calls.
 *
 * @param events     Every AgentStreamEvent received so far, in arrival
 *                    order (useAnalysisStream's `events`).
 * @param isComplete  True once the stream's terminal event (`is_final`)
 *                    has arrived (useAnalysisStream's `isComplete`).
 *                    Used to flip any agent that never got a turn (an
 *                    early pipeline failure, most commonly) from
 *                    "waiting"/"thinking" to "skipped" instead of
 *                    leaving its card spinning forever after the job
 *                    has already terminated.
 */
export function deriveAgentCards(
  events: readonly AgentStreamEvent[],
  isComplete: boolean,
): AgentCardViewModel[] {
  return COMMITTEE_ROSTER.map((entry): AgentCardViewModel => {
    const latest = latestEventFor(events, entry.nodeName);

    if (latest !== undefined) {
      return {
        ...entry,
        state: latest.status === "failed" ? "failed" : "complete",
        outputPreview: latest.output_preview,
      };
    }

    if (isComplete) {
      return { ...entry, state: "skipped", outputPreview: null };
    }

    const priorRoundsComplete =
      entry.round === 1 ||
      (entry.round === 2 && roundIsComplete(1, events)) ||
      (entry.round === 3 && roundIsComplete(1, events) && roundIsComplete(2, events));

    return {
      ...entry,
      state: priorRoundsComplete ? "thinking" : "waiting",
      outputPreview: null,
    };
  });
}
