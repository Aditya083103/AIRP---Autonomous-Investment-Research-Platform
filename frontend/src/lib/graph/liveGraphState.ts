// frontend/src/lib/graph/liveGraphState.ts
// AIRP -- live per-node status derivation for the pipeline graph (T-096;
// T-097 adds the debate_loop cycle edge's own live state below)
//
// Turns the raw AgentStreamEvent[] from useAnalysisStream.ts into one
// PipelineNodeStatus per node in the static topology
// (src/lib/graph/pipelineTopology.ts). Deliberately a pure function with
// no React, no timers, and no subscription of its own -- the exact same
// "given identical inputs, always the same output" contract
// src/lib/agentProgress.ts's deriveAgentCards already establishes for
// the card view, so a given event sequence produces a checkable,
// deterministic set of node statuses with no timing, mocked sockets, or
// async waiting involved in the test for this module.
//
// Why this module does NOT need agentProgress.ts's "thinking" heuristic
// ------------------------------------------------------------------------
// agentProgress.ts's own docstring explains, at length, why it has to
// INFER a "thinking" state from round order: as of T-049, the backend
// only ever announced a node's COMPLETION, never its start. T-095 closed
// that gap -- every node now also publishes a NODE_STARTED event
// (event_type: "node_started") the instant it begins, before any of its
// real work runs. This module reads that real signal directly instead of
// guessing from round order: a node is "running" if and only if its own
// most recent event is a started event, full stop. This is also exactly
// why the 4 parallel research nodes "animate simultaneously" (T-096's
// second acceptance criterion) requires no special-case code here at
// all -- each of the 4 nodes' status is derived independently from its
// own latest event, and since the backend dispatches all 4 in the same
// LangGraph Send super-step (see backend/graph/graph.py's topology
// comment), their real NODE_STARTED events arrive close together and
// each flips to "running" the moment its own event lands.
//
// T-097 addition: deriveDebateLoopEdgeState
// -------------------------------------------
// Uses the exact same "read the real signal, don't guess" principle for
// the ONE thing deriveNodeStatuses deliberately doesn't answer: is the
// debate_loop -> contrarian_investor cycle edge (T-040's
// route_after_contrarian DEBATE_AGAIN branch, T-094's
// DEBATE_LOOP_EDGE_ID) currently "in motion", and which of its (at most
// 2, per backend.graph.debate.MAX_DEBATE_ROUNDS) rounds is it on? See
// that function's own docstring below for the full reasoning -- in
// short, the edge is "active" whenever contrarian_investor OR
// debate_loop is itself "running", which naturally toggles on, off,
// then on again across a real 2-round debate with zero extra
// event-counting logic beyond a single filter over already-published
// NODE_STARTED events.

import { EVENT_TYPE_NODE_STARTED, type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import {
  NODE_CONTRARIAN,
  NODE_DEBATE_LOOP,
  NODE_END,
  NODE_START,
  PIPELINE_NODE_IDS,
  type PipelineNodeData,
} from "@/lib/graph/pipelineTopology";

/**
 * One pipeline node's live state, as shown in the graph:
 *   - "pending": no event for this node has arrived yet.
 *   - "running": this node's own most recent event is a started event.
 *   - "done":    this node's own most recent event is a completed event
 *                whose pipeline status was not "failed".
 *   - "failed":  this node's own most recent event is a completed event
 *                whose pipeline status was "failed".
 */
export type PipelineNodeStatus = "pending" | "running" | "done" | "failed";

/** PipelineNodeData (T-094) plus the one live field LiveGraphNode (T-096) renders on top. */
export interface LiveGraphNodeData extends PipelineNodeData {
  status: PipelineNodeStatus;
}

/**
 * The most recent event for `nodeName`, or undefined if none has
 * arrived yet. Mirrors src/lib/agentProgress.ts's identical
 * `latestEventFor` helper -- both modules need the same "walk backward,
 * return the first match" lookup, kept as two small independent copies
 * (rather than one shared export) since agentProgress.ts's version is
 * scoped to the 8-agent committee roster and this one is scoped to all
 * 15 real pipeline nodes; a shared helper would need a third file for a
 * six-line function with no other behaviour to factor out.
 */
function latestEventForNode(
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
 * Derive one PipelineNodeStatus per real pipeline node (every id in
 * PIPELINE_NODE_IDS) plus the two boundary sentinels (NODE_START,
 * NODE_END), from the current event stream.
 *
 * A missing/undefined `event_type` (any event that predates T-095, or a
 * hand-built test fixture) is treated as a completed event -- the same
 * default backend.services.ws_broadcaster.cast_event itself applies --
 * never as "running", so an old-shaped event can never get a node stuck
 * mid-pulse.
 *
 * @param events     Every AgentStreamEvent received so far, in arrival
 *                    order (useAnalysisStream's `events`).
 * @param isComplete  True once the stream's terminal event (`is_final`)
 *                    has arrived (useAnalysisStream's `isComplete`) --
 *                    used only to decide NODE_END's own status, since
 *                    END is a LangGraph sentinel with no real event of
 *                    its own to key off.
 */
export function deriveNodeStatuses(
  events: readonly AgentStreamEvent[],
  isComplete: boolean,
): Record<string, PipelineNodeStatus> {
  const statuses: Record<string, PipelineNodeStatus> = {};

  for (const nodeId of PIPELINE_NODE_IDS) {
    const latest = latestEventForNode(events, nodeId);

    if (latest === undefined) {
      statuses[nodeId] = "pending";
    } else if (latest.event_type === EVENT_TYPE_NODE_STARTED) {
      statuses[nodeId] = "running";
    } else if (latest.status === "failed") {
      statuses[nodeId] = "failed";
    } else {
      statuses[nodeId] = "done";
    }
  }

  const lastEvent = events.length > 0 ? events[events.length - 1] : undefined;
  const pipelineFailed = lastEvent?.status === "failed";

  // START has no real backend event of its own -- it is "done" (i.e.
  // "the pipeline has been entered") the instant any event at all has
  // arrived, since that can only happen after LangGraph traversed the
  // START -> planner edge.
  statuses[NODE_START] = events.length > 0 ? "done" : "pending";

  // END likewise has no real event -- it only "completes" once the
  // stream's own terminal event has arrived, and reads as "failed"
  // rather than "done" if the pipeline's last reported status was
  // itself "failed", so a failed run does not show a falsely-successful
  // green END node.
  statuses[NODE_END] = isComplete ? (pipelineFailed ? "failed" : "done") : "pending";

  return statuses;
}

/**
 * The debate_loop <-> contrarian_investor cycle edge's own live state
 * (T-097) -- separate from PipelineNodeStatus because an EDGE, not a
 * node, is what T-097's "round-trip pulse" acceptance criterion is
 * about; deriveNodeStatuses already tells the two nodes on either end
 * of the cycle their own status, but says nothing about whether the
 * CYCLE ITSELF should currently read as "in motion".
 */
export interface DebateLoopEdgeState {
  /**
   * True while the debate loop is actively in a round -- i.e. while
   * contrarian_investor or debate_loop is itself "running". False
   * before the debate has started, in the (typically brief) gap
   * between one round's debate_loop completing and the next round's
   * contrarian_investor starting, and once the debate has concluded
   * for good (routed on to risk_officer).
   */
  active: boolean;
  /**
   * Which debate round is currently in progress -- 1 or 2, matching
   * backend.graph.debate's MAX_DEBATE_ROUNDS cap -- or null before the
   * debate has started. Counts contrarian_investor's own NODE_STARTED
   * events rather than debate_loop's, since contrarian always starts
   * first in every round; using debate_loop's own count would report
   * "no round yet" for the entire first half of round 1, while
   * contrarian is already visibly running.
   */
  currentRound: 1 | 2 | null;
}

/**
 * Derive the debate_loop cycle edge's live state from the event
 * stream, for T-097's LiveGraphView to style the DEBATE_AGAIN edge
 * with: animated + full strength while `active`, dimmed and static
 * otherwise.
 *
 * Why this reads as a "round-trip pulse... across its 2 rounds"
 * with no explicit round-boundary bookkeeping: `active` is computed
 * fresh from each render's `nodeStatuses` (already computed by
 * deriveNodeStatuses for the same `events`), and because a node's
 * status always reflects only its OWN latest event, `active` flips
 * true the instant contrarian_investor starts round 1, false once
 * debate_loop completes round 1 (and contrarian_investor has not yet
 * restarted), true again the instant contrarian_investor starts round
 * 2, and false for good once debate_loop completes round 2. Two
 * separate true/false/true/false cycles, driven entirely by the same
 * per-node "latest event wins" rule deriveNodeStatuses already uses --
 * nothing here has to remember "which round already pulsed."
 *
 * @param events        Every AgentStreamEvent received so far, in
 *                       arrival order (useAnalysisStream's `events`).
 * @param nodeStatuses   The output of deriveNodeStatuses for the same
 *                       `events` -- passed in rather than recomputed,
 *                       so a caller building both a node's status and
 *                       the edge's state in the same render (T-097's
 *                       LiveGraphView) does exactly one status pass.
 */
export function deriveDebateLoopEdgeState(
  events: readonly AgentStreamEvent[],
  nodeStatuses: Record<string, PipelineNodeStatus>,
): DebateLoopEdgeState {
  const active =
    nodeStatuses[NODE_CONTRARIAN] === "running" || nodeStatuses[NODE_DEBATE_LOOP] === "running";

  const contrarianRoundsStarted = events.filter(
    (event) => event.agent === NODE_CONTRARIAN && event.event_type === EVENT_TYPE_NODE_STARTED,
  ).length;

  let currentRound: 1 | 2 | null = null;
  if (contrarianRoundsStarted >= 1) {
    currentRound = contrarianRoundsStarted >= 2 ? 2 : 1;
  }

  return { active, currentRound };
}
