// frontend/src/lib/debateTranscript.ts
// AIRP -- Debate transcript derivation (T-060)
//
// Turns the raw AgentStreamEvent[] from useAnalysisStream.ts (T-049)
// into an ordered, per-round transcript the Debate Viewer can render as
// a timeline/chat UI. This module is deliberately the "transcript"
// counterpart to src/lib/agentProgress.ts's "cards" view of the exact
// same event stream:
//
//   - agentProgress.ts collapses each agent down to its LATEST event,
//     because a progress card only ever shows "where is this agent
//     right now".
//   - debateTranscript.ts keeps EVERY event as its own message, in
//     arrival order, because the literal T-060 acceptance criterion is
//     "all debate rounds visible" as a conversation -- a debate-loop
//     agent (Risk Officer, Contrarian Investor) that speaks more than
//     once across debate rounds must show up as more than one message,
//     not have its earlier remarks silently overwritten.
//
// Like agentProgress.ts, this is a pure function with no React and no
// subscription of its own: the same `events` array always produces the
// same transcript, which is what makes it unit-testable without any
// WebSocket mocking (see debateTranscript.test.ts).

import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import { COMMITTEE_ROSTER, type CommitteeRosterEntry } from "@/lib/agentProgress";

/** One committee member's turn in the debate, ready to render as a message. */
export interface DebateTranscriptMessage {
  /** Stable React key -- arrival index plus node name (an agent may speak twice). */
  id: string;
  /** Exact LangGraph node name from backend.graph.nodes' NODE_* constants. */
  nodeName: string;
  displayName: string;
  seat: number;
  round: 1 | 2 | 3;
  /** Raw status string off the wire (e.g. "running", "completed", "failed"). */
  status: string;
  /** The message body -- AgentStreamEvent.output_preview, unmodified. */
  content: string;
  /** 1-based position of this message among ALL agent messages, in arrival order. */
  turn: number;
}

/** Round labels shown as section dividers in the timeline. */
export const DEBATE_ROUND_LABELS: Record<1 | 2 | 3, string> = {
  1: "Round 1 — Research findings",
  2: "Round 2 — Debate & challenge",
  3: "Round 3 — Final decision",
};

const ROSTER_BY_NODE_NAME: ReadonlyMap<string, CommitteeRosterEntry> = new Map(
  COMMITTEE_ROSTER.map((entry) => [entry.nodeName, entry]),
);

/**
 * Build the full ordered transcript from a raw event stream.
 *
 * Non-committee pipeline nodes (planner, research_join, error_handler,
 * sentiment_escalation, debate_loop, report_generator, pdf_export --
 * see backend/graph/nodes.py's NODE_* constants) are silently skipped:
 * the debate transcript is scoped to what the 8 committee members
 * said, the same scope src/lib/agentProgress.ts already established
 * for the progress board.
 */
export function buildDebateTranscript(
  events: readonly AgentStreamEvent[],
): DebateTranscriptMessage[] {
  const messages: DebateTranscriptMessage[] = [];

  events.forEach((event, index) => {
    const roster = ROSTER_BY_NODE_NAME.get(event.agent);
    if (roster === undefined) {
      return;
    }
    messages.push({
      id: `${index}-${event.agent}`,
      nodeName: roster.nodeName,
      displayName: roster.displayName,
      seat: roster.seat,
      round: roster.round,
      status: event.status,
      content: event.output_preview,
      turn: messages.length + 1,
    });
  });

  return messages;
}

/** All messages for a given round, preserving arrival order. */
export function messagesForRound(
  messages: readonly DebateTranscriptMessage[],
  round: 1 | 2 | 3,
): DebateTranscriptMessage[] {
  return messages.filter((message) => message.round === round);
}
