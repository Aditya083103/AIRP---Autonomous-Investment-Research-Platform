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
//
// B10: the state badge and body content are each a motion.span/motion.div
// keyed on `agent.state` -- React remounts them (not the whole card, so
// AgentProgressBoard's `key={card.nodeName}` identity and any of its own
// layout/scroll position is untouched) whenever the committee moves this
// agent from one state to the next, and framer-motion's `initial`+
// `animate` on the freshly-mounted element gives that a soft fade/rise
// instead of an instant text swap -- "agent-card state transitions" from
// the work order. A plain span/div under usePrefersReducedMotion(), per
// its explicit accessibility constraint.

import { motion } from "framer-motion";

import { TypingIndicator } from "@/components/progress/TypingIndicator";
import { Card } from "@/components/ui";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";
import { type AgentCardViewModel } from "@/lib/agentProgress";
import { cn } from "@/lib/cn";

// Matches src/components/landing/CommitteeSection.tsx's own ROUNDS accent
// colours -- the architecture doc's literal fill hue
// (docs/AIRP_Architecture.drawio) for each round -- so a seat here and its
// counterpart on the marketing page read as the same agent.
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
  thinking: "bg-brand-500/15 text-brand-600",
  complete: "bg-verdict-buy/15 text-verdict-buy",
  failed: "bg-verdict-sell/15 text-verdict-sell",
  skipped: "bg-line text-muted",
};

interface AgentCardProps {
  agent: AgentCardViewModel;
}

/** initial/animate for a freshly-(re)mounted state badge/body -- omitted entirely under reduced motion, which leaves the motion.* element fully inert (no forced opacity/transform at all). */
function useStateTransitionProps() {
  const prefersReducedMotion = usePrefersReducedMotion();
  if (prefersReducedMotion) {
    return {};
  }
  return {
    initial: { opacity: 0, y: 4 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.25, ease: "easeOut" as const },
  };
}

export function AgentCard({ agent }: AgentCardProps): JSX.Element {
  const transitionProps = useStateTransitionProps();

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
        <motion.span
          key={agent.state}
          className={cn(
            "shrink-0 rounded-full px-2.5 py-1 text-xs font-medium",
            STATE_BADGE_CLASSES[agent.state],
          )}
          {...transitionProps}
        >
          {STATE_LABEL[agent.state]}
        </motion.span>
      </div>

      <motion.div key={agent.state} className="flex-1" {...transitionProps}>
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
      </motion.div>
    </Card>
  );
}
