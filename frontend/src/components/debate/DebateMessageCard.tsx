// frontend/src/components/debate/DebateMessageCard.tsx
// AIRP -- Debate Viewer message bubble (T-060)
//
// Renders one DebateTranscriptMessage (src/lib/debateTranscript.ts) as a
// single timeline entry: a colour-coded avatar + left border unique to
// the speaking agent, a status pill, and expand/collapse for long
// messages. Colour-per-agent is deliberately its own palette
// (AGENT_ACCENTS below) rather than AgentCard.tsx's per-ROUND accent --
// the debate viewer's whole point is telling 8 individual voices apart
// inside a single round, so two agents sharing a round must not share
// a colour the way they intentionally do on the progress board.

import { useState } from "react";

import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";
import { type DebateTranscriptMessage } from "@/lib/debateTranscript";

/** One accent colour per committee seat -- stable across renders and re-runs. */
const AGENT_ACCENTS: Record<string, string> = {
  fundamental_analyst: "#1D4ED8",
  technical_analyst: "#0EA5E9",
  sentiment_analyst: "#7C3AED",
  macro_economist: "#0D9488",
  risk_officer: "#B91C1C",
  contrarian_investor: "#C2410C",
  valuation_agent: "#A16207",
  portfolio_manager: "#065F46",
};

const DEFAULT_ACCENT = "#5B6472";

/** Messages longer than this are collapsed by default, with a toggle to expand. */
const PREVIEW_CHAR_LIMIT = 160;

function initialsFor(displayName: string): string {
  const words = displayName.split(" ").filter(Boolean);
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? words[words.length - 1]?.[0] ?? "" : "";
  return `${first}${last}`.toUpperCase();
}

function statusTone(status: string): "buy" | "sell" | "brand" | "neutral" {
  if (status === "completed") return "buy";
  if (status === "failed") return "sell";
  if (status === "running") return "brand";
  return "neutral";
}

interface DebateMessageCardProps {
  message: DebateTranscriptMessage;
}

export function DebateMessageCard({ message }: DebateMessageCardProps): JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const accent = AGENT_ACCENTS[message.nodeName] ?? DEFAULT_ACCENT;
  const isLong = message.content.length > PREVIEW_CHAR_LIMIT;
  const truncated = `${message.content.slice(0, PREVIEW_CHAR_LIMIT).trimEnd()}…`;
  const displayedContent = !isLong || expanded ? message.content : truncated;

  return (
    <div
      className="flex gap-3 rounded-card border border-line border-l-4 bg-surface p-4 shadow-card"
      style={{ borderLeftColor: accent }}
      data-agent={message.nodeName}
      data-turn={message.turn}
    >
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
          "text-xs font-semibold text-white",
        )}
        style={{ backgroundColor: accent }}
        aria-hidden="true"
      >
        {initialsFor(message.displayName)}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
            <p className="text-sm font-semibold text-ink">{message.displayName}</p>
            <span className="font-mono text-xs text-muted">Seat {message.seat}</span>
          </div>
          <Badge tone={statusTone(message.status)}>{message.status}</Badge>
        </div>

        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">
          {displayedContent}
        </p>

        {isLong ? (
          <button
            type="button"
            onClick={() => setExpanded((previous) => !previous)}
            aria-expanded={expanded}
            className={cn(
              "mt-2 font-mono text-xs font-semibold uppercase tracking-wide text-brand-600",
              "hover:text-brand-700 hover:underline",
            )}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
