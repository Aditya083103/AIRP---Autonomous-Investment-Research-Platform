// frontend/src/components/progress/AgentProgressBoard.tsx
// AIRP -- Live agent progress board (T-059)
//
// The actual T-059 deliverable: consumes useAnalysisStream's raw event
// list, derives each card's state via src/lib/agentProgress.ts, and
// renders the 8 cards grouped into the same three execution rounds
// CommitteeSection.tsx (T-055) uses on the marketing page. Also shows
// the connection lifecycle (idle/connecting/open/closed/error) and an
// overall progress bar driven by the stream's own progress_percent, so
// a stalled/dropped connection is visibly different from "the pipeline
// is just still running."

import { AgentCard } from "@/components/progress/AgentCard";
import { ProgressBar, Spinner } from "@/components/ui";
import {
  type AgentStreamEvent,
  type AnalysisStreamConnectionStatus,
} from "@/hooks/useAnalysisStream";
import { COMMITTEE_ROSTER, deriveAgentCards } from "@/lib/agentProgress";
import { cn } from "@/lib/cn";

const ROUND_TITLES: Record<1 | 2 | 3, string> = {
  1: "Round 1 — Parallel research",
  2: "Round 2 — Debate & challenge",
  3: "Final call",
};

const ROUND_GRID_CLASSES: Record<1 | 2 | 3, string> = {
  1: "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4",
  2: "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3",
  3: "grid grid-cols-1 gap-5 sm:max-w-sm",
};

function describeConnection(
  connectionStatus: AnalysisStreamConnectionStatus,
  isComplete: boolean,
): string {
  if (connectionStatus === "connecting") {
    return "Connecting to the committee…";
  }
  if (connectionStatus === "open" && !isComplete) {
    return "Live — streaming agent updates";
  }
  if (connectionStatus === "closed" && isComplete) {
    return "Analysis complete";
  }
  if (connectionStatus === "error") {
    return "Connection error";
  }
  return connectionStatus;
}

interface AgentProgressBoardProps {
  events: readonly AgentStreamEvent[];
  isComplete: boolean;
  progressPercent: number;
  connectionStatus: AnalysisStreamConnectionStatus;
  error: string | null;
}

export function AgentProgressBoard({
  events,
  isComplete,
  progressPercent,
  connectionStatus,
  error,
}: AgentProgressBoardProps): JSX.Element {
  const cards = deriveAgentCards(events, isComplete);
  const rounds: (1 | 2 | 3)[] = [1, 2, 3];

  return (
    <div>
      <div className="flex items-center gap-2 text-sm text-muted">
        {connectionStatus === "connecting" ? <Spinner size="sm" /> : null}
        <span>{describeConnection(connectionStatus, isComplete)}</span>
      </div>

      <div className="mt-3">
        <ProgressBar value={progressPercent} label="Overall progress" />
      </div>

      {error ? (
        <p role="alert" className="mt-4 text-sm text-verdict-sell">
          {error}
        </p>
      ) : null}

      <div className="mt-8 space-y-10">
        {rounds.map((round) => (
          <div key={round}>
            <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-ink">
              {ROUND_TITLES[round]}
            </h3>
            <div className={cn("mt-4", ROUND_GRID_CLASSES[round])}>
              {cards
                .filter((card) => card.round === round)
                .map((card) => (
                  <AgentCard key={card.nodeName} agent={card} />
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Re-exported so consumers (e.g. AnalysisResultPage) can check "did every
// committee member finish" without re-deriving the roster length themselves.
export const COMMITTEE_SIZE = COMMITTEE_ROSTER.length;
