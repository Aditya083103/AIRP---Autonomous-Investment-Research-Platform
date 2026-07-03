// frontend/src/components/debate/DebateViewer.tsx
// AIRP -- Debate Viewer (T-060)
//
// The T-060 deliverable: a timeline/chat UI showing the committee's
// agents "speaking" in the order their AgentStreamEvent arrived,
// grouped under the same three execution rounds AgentProgressBoard.tsx
// (T-059) and CommitteeSection.tsx (T-055) use. Consumes the identical
// `events` array useAnalysisStream (T-049) already produces -- this
// viewer adds no new backend contract, it is a second way of looking
// at data the frontend already has.
//
// "All debate rounds visible" (acceptance criterion) means all three
// round sections always render, even before any agent in that round
// has spoken -- an empty round shows a placeholder rather than
// disappearing, the same way AgentProgressBoard always shows all 8
// cards regardless of stream progress.

import { DebateMessageCard } from "@/components/debate/DebateMessageCard";
import { type AgentStreamEvent } from "@/hooks/useAnalysisStream";
import { cn } from "@/lib/cn";
import {
  buildDebateTranscript,
  DEBATE_ROUND_LABELS,
  messagesForRound,
} from "@/lib/debateTranscript";

const ROUNDS: readonly (1 | 2 | 3)[] = [1, 2, 3];

interface DebateViewerProps {
  /** Every AgentStreamEvent received so far, in arrival order. */
  events: readonly AgentStreamEvent[];
}

export function DebateViewer({ events }: DebateViewerProps): JSX.Element {
  const messages = buildDebateTranscript(events);

  return (
    <div className="space-y-10" data-testid="debate-viewer">
      {messages.length === 0 ? (
        <p className="text-sm text-muted">
          The debate transcript will appear here once the committee starts speaking.
        </p>
      ) : null}

      {ROUNDS.map((round) => {
        const roundMessages = messagesForRound(messages, round);
        return (
          <section key={round} aria-label={DEBATE_ROUND_LABELS[round]}>
            <div className="flex items-center gap-3">
              <h3
                className={cn(
                  "whitespace-nowrap font-mono text-sm font-semibold uppercase",
                  "tracking-wide text-ink",
                )}
              >
                {DEBATE_ROUND_LABELS[round]}
              </h3>
              <span className="h-px flex-1 bg-line" aria-hidden="true" />
            </div>

            <div className="mt-4 space-y-4">
              {roundMessages.length === 0 ? (
                <p className="text-sm text-muted">No messages yet in this round.</p>
              ) : (
                roundMessages.map((message) => (
                  <DebateMessageCard key={message.id} message={message} />
                ))
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
