// frontend/src/lib/graph/liveGraphState.ts
// AIRP -- live per-node status derivation for the pipeline graph (T-096)
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

import { EVENT_TYPE_NODE_STARTED, type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import {
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
