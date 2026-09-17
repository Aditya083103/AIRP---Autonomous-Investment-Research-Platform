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

/**
 * LangGraph join/barrier node that only ever completes after all 4
 * round-1 research agents (fundamental_analyst, technical_analyst,
 * sentiment_analyst, macro_economist) have -- see
 * backend/graph/graph.py's edges (all 4 point into NODE_RESEARCH_JOIN)
 * and backend/routers/websocket.py's `_snapshot_to_events`, which
 * already expands a replayed `research_join` completion into its own 4
 * agent events for exactly this reason. Not itself a COMMITTEE_ROSTER
 * entry (no card is rendered for it) -- used only as corroborating
 * evidence that round 1 finished, in `roundIsComplete` and
 * `deriveAgentCards` below (see the B3 fix note on `deriveAgentCards`).
 */
const NODE_RESEARCH_JOIN = "research_join";

/**
 * The non-parallel portion of the pipeline, in the exact sequential
 * order backend/graph/graph.py's build_graph() wires: research_join ->
 * contrarian_investor -> debate_loop -> risk_officer -> valuation_agent
 * -> portfolio_manager -> report_generator -> pdf_export. Every one of
 * these nodes can only ever run after every node before it in this
 * list has already completed -- there is no fan-out or branching once
 * research_join fires (route_after_contrarian's debate loop always
 * eventually proceeds to risk_officer; the only other conditional
 * branches, error_handler/sentiment_escalation, both land back on
 * contrarian_investor before this point, so they do not appear here).
 * Used by `hasLaterPipelineEvidence` below as the general form of the
 * `research_join` reconciliation this module already applied to Round
 * 1: an event for ANY node in this list is authoritative proof every
 * earlier node in the list also ran, even when this live connection
 * never received that earlier node's own event.
 */
const SEQUENTIAL_PIPELINE_ORDER: readonly string[] = [
  NODE_RESEARCH_JOIN,
  "contrarian_investor",
  "debate_loop",
  "risk_officer",
  "valuation_agent",
  "portfolio_manager",
  "report_generator",
  "pdf_export",
];

/**
 * True when some node LATER than `anchorNodeName` in
 * `SEQUENTIAL_PIPELINE_ORDER` has an event -- proof `anchorNodeName`
 * itself must have already run, regardless of whether this connection
 * ever received its own event.
 *
 * Generalises the `research_join` special-case B3 fix (see this
 * module's docstring and `roundIsComplete`) to every sequential node
 * after it: a live WebSocket connection can miss ANY single node's
 * broadcast (a fire-and-forget, at-most-once publish -- see
 * backend/services/ws_broadcaster.py's own documented limitation, and
 * backend/routers/websocket.py's `_catch_up_if_already_terminal`,
 * which backfills exactly this same evidence server-side after a
 * heartbeat notices the job already finished). Without this check, a
 * seat whose OWN event was lost but whose successor's event arrived
 * would still wrongly render "skipped" once the stream closes -- the
 * exact "Risk Officer / Contrarian Investor / Valuation Agent /
 * Portfolio Manager show 'Did not run for this analysis'" bug, even
 * though later evidence already proves the node ran.
 *
 * @param anchorNodeName Must be a member of SEQUENTIAL_PIPELINE_ORDER
 *   (or NODE_RESEARCH_JOIN, used as the round-1 agents' anchor -- see
 *   `deriveAgentCards`). Returns false for any other value.
 */
function hasLaterPipelineEvidence(
  anchorNodeName: string,
  events: readonly AgentStreamEvent[],
): boolean {
  const anchorIndex = SEQUENTIAL_PIPELINE_ORDER.indexOf(anchorNodeName);
  if (anchorIndex === -1) {
    return false;
  }
  return SEQUENTIAL_PIPELINE_ORDER.slice(anchorIndex + 1).some(
    (nodeName) => latestEventFor(events, nodeName) !== undefined,
  );
}

function roundIsComplete(round: 1 | 2 | 3, events: readonly AgentStreamEvent[]): boolean {
  if (round === 1 && latestEventFor(events, NODE_RESEARCH_JOIN) !== undefined) {
    // research_join cannot complete unless all 4 round-1 agents already
    // have -- authoritative even if this live connection missed one of
    // their own individual events (B3).
    return true;
  }
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
 *
 * B3 fix: a seat only ever renders "skipped" once `isComplete` is true
 * (the job's terminal state) -- while the job is still running, a seat
 * with no event of its own always renders "waiting"/"thinking", never
 * "skipped". That alone does not fully close the bug this fix targets:
 * a live connection can miss an individual round-1 research agent's own
 * NODE_STARTED/NODE_COMPLETED events (e.g. it connected slightly after
 * that agent's Send-parallel branch already fired -- see
 * backend/routers/websocket.py's own documented connect-timing races),
 * so by the time the job's real terminal event arrives through THIS
 * SAME live connection, that seat's local event history is still empty
 * and it would wrongly render "skipped" even though the agent
 * genuinely ran (a full page reload's fresh replay,
 * `_snapshot_to_events`, already gets this right by expanding
 * `research_join` into its 4 upstream agents -- see that function's own
 * docstring). Reconciling the live stream against `research_join`'s own
 * completion event the same way closes that gap without requiring a
 * reload: `research_join` cannot complete unless all 4 round-1 agents
 * already have, so its arrival is authoritative proof a round-1 seat
 * with no event of its own still actually ran.
 */
export function deriveAgentCards(
  events: readonly AgentStreamEvent[],
  isComplete: boolean,
): AgentCardViewModel[] {
  const researchJoin = latestEventFor(events, NODE_RESEARCH_JOIN);

  return COMMITTEE_ROSTER.map((entry): AgentCardViewModel => {
    const latest = latestEventFor(events, entry.nodeName);

    if (latest !== undefined) {
      return {
        ...entry,
        state: latest.status === "failed" ? "failed" : "complete",
        outputPreview: latest.output_preview,
      };
    }

    if (entry.round === 1 && researchJoin !== undefined) {
      return {
        ...entry,
        state: researchJoin.status === "failed" ? "failed" : "complete",
        outputPreview: researchJoin.output_preview,
      };
    }

    // General downstream-evidence fallback (see hasLaterPipelineEvidence's
    // docstring): round-1 agents anchor on research_join's position in
    // SEQUENTIAL_PIPELINE_ORDER (covers the case where research_join's
    // OWN event was also missed but something after it arrived); round
    // 2/3 seats anchor on their own node name directly.
    const anchorNodeName = entry.round === 1 ? NODE_RESEARCH_JOIN : entry.nodeName;
    if (hasLaterPipelineEvidence(anchorNodeName, events)) {
      return { ...entry, state: "complete", outputPreview: null };
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
