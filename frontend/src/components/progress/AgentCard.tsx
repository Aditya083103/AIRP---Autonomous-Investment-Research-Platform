// frontend/src/components/progress/AgentCard.tsx
// AIRP -- Agent progress card (T-059)
//
// Renders one AgentCardViewModel (src/lib/agentProgress.ts). State ->
// visual mapping is the literal acceptance criterion: "Waiting",
// "Thinking" (with TypingIndicator), and "Complete" (with the output
// preview) -- plus "Failed" and "Skipped" for the two terminal
// non-happy-paths deriveAgentCards can produce. Accent colours reuse
// the exact hex values CommitteeSection.tsx (T-055) already assigned
// per round, so a card here and its counterpart on the marketing page
// are visually the same "agent", not two independently-designed looks.

import { TypingIndicator } from "@/components/progress/TypingIndicator";
import { Card } from "@/components/ui";
import { type AgentCardViewModel } from "@/lib/agentProgress";
import { cn } from "@/lib/cn";

const ROUND_ACCENT: Record<1 | 2 | 3, string> = {
  1: "#1D4ED8",
  2: "#B91C1C",
  3: "#065F46",
};

const STATE_LABEL: Record<AgentCardViewModel["state"], string> = {
  waiting: "Waiting",
  thinking: "Thinking",
  complete: "Complete",
  failed: "Failed",
  skipped: "Skipped",
};

const STATE_BADGE_CLASSES: Record<AgentCardViewModel["state"], string> = {
  waiting: "bg-line text-muted",
  thinking: "bg-brand-50 text-brand-700",
  complete: "bg-verdict-buy/15 text-verdict-buy",
  failed: "bg-verdict-sell/15 text-verdict-sell",
  skipped: "bg-line text-muted",
};

interface AgentCardProps {
  agent: AgentCardViewModel;
}

export function AgentCard({ agent }: AgentCardProps): JSX.Element {
  return (
    <Card
      noPadding
      className="flex h-full flex-col gap-3 border-t-4 p-5"
      style={{ borderTopColor: ROUND_ACCENT[agent.round] }}
      data-agent={agent.nodeName}
      data-state={agent.state}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-xs text-muted">Seat {agent.seat}</p>
          <h3 className="mt-1 text-sm font-semibold text-ink">{agent.displayName}</h3>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full px-2.5 py-1 text-xs font-medium",
            STATE_BADGE_CLASSES[agent.state],
          )}
        >
          {STATE_LABEL[agent.state]}
        </span>
      </div>

      <div className="flex-1">
        {agent.state === "thinking" ? (
          <div className="flex items-center gap-2 text-sm text-muted">
            <TypingIndicator />
            <span>Working…</span>
          </div>
        ) : agent.state === "complete" || agent.state === "failed" ? (
          <p className="text-sm leading-relaxed text-ink">{agent.outputPreview}</p>
        ) : agent.state === "skipped" ? (
          <p className="text-sm text-muted">Did not run for this analysis.</p>
        ) : (
          <p className="text-sm text-muted">Waiting for its turn.</p>
        )}
      </div>
    </Card>
  );
}
