// frontend/src/components/landing/CommitteeSection.tsx
// Landing page — the "8 agents diagram" acceptance criterion.
// Deliberately mirrors docs/AIRP_Architecture.drawio's hue family rather
// than inventing a fresh visual language: research agents keep the
// diagram's blue, the debate/challenge agents keep its red, and the
// Portfolio Manager keeps its green. Grouping into three rounds
// (parallel research -> debate -> final call) reflects the actual
// LangGraph execution order, not an arbitrary layout choice.
//
// ISSUE 5: each accent below (#60A5FA/#F87171/#34D399) is one step
// brighter than the architecture doc's literal fill colour
// (#1D4ED8/#B91C1C/#065F46) -- those were tuned as a thin border accent
// against a WHITE card; against this pass's dark `bg-surface` card the
// same dark hues lose almost all contrast, so each moves to its
// brighter Tailwind neighbour. Kept identical to
// src/components/progress/AgentCard.tsx's own ROUND_ACCENT (see that
// file's own ISSUE 5 comment) so a seat here and its counterpart on the
// live progress view are still visually the same agent.
//
// B10: each seat's card is wrapped in Reveal (staggered fade/rise-in by
// seat number, so the whole 8-seat roster cascades in roughly the order
// a reader's eye already follows -- round 1 first, seat 8 last) and
// TiltCard (a subtle pointer-tracked 3D tilt on hover), the same
// micro-interaction treatment given to every other card grid this unit
// touches.
//
// Landing-page redesign: each round's ordinal ("Round 1"/"Round 2"/
// "Round 3") now renders as its own Badge next to the round's plain-
// English title, instead of being baked into the title string with an
// em dash ("Round 1 — Parallel research") -- the numbering is still
// real information (it genuinely is the LangGraph execution order), it
// is just no longer expressed as decorative tracked-out text. A
// RoundConnector (a short vertical line + arrow) between each round
// makes that same execution order visible as a flow, foreshadowing the
// real LangGraph state machine this diagram is a simplified stand-in
// for, rather than leaving the sequence to be inferred purely from
// vertical stacking order.
//
// Card hierarchy: AgentCard is this page's "secondary" card type (a
// repeated grid item, not the section's own anchor) -- it drops the
// generic border every Card renders by default (via `border-transparent`,
// see AgentCard below) and keeps only the shadow plus its own
// round-coloured `border-t-4` accent stripe, which stays fully opaque
// because it is set as an inline style on that one side specifically.

import { Fragment } from "react";

import { Reveal } from "@/components/motion/Reveal";
import { TiltCard } from "@/components/three/TiltCard";
import { Badge, Card } from "@/components/ui";
import { cn } from "@/lib/cn";

interface CommitteeAgent {
  readonly seat: number;
  readonly name: string;
  readonly mandate: string;
  readonly tools: string;
  readonly output: string;
  /** Matches the fill colour used for this agent in AIRP_Architecture.drawio. */
  readonly accent: string;
}

interface CommitteeRound {
  readonly id: string;
  /** Rendered as its own Badge -- see this file's own "Landing-page redesign" note above. */
  readonly roundLabel: string;
  readonly title: string;
  readonly description: string;
  readonly agents: readonly CommitteeAgent[];
}

const ROUNDS: readonly CommitteeRound[] = [
  {
    id: "research",
    roundLabel: "Round 1",
    title: "Parallel research",
    description: "Four analysts gather evidence at the same time; none sees the others yet.",
    agents: [
      {
        seat: 1,
        name: "Fundamental Analyst",
        mandate:
          "Revenue growth, profit margins, free cash flow, debt, and balance-sheet health over 4 years.",
        tools: "yFinance, Alpha Vantage",
        output: "FundamentalAnalysis (score 1–10)",
        accent: "#60A5FA",
      },
      {
        seat: 2,
        name: "Technical Analyst",
        mandate: "Price trend, 50d/200d moving averages, RSI, momentum, and 52-week positioning.",
        tools: "yFinance OHLCV",
        output: "TechnicalAnalysis (BUY/HOLD/SELL)",
        accent: "#60A5FA",
      },
      {
        seat: 3,
        name: "News Sentiment Agent",
        mandate: "Scores the last 30 days of news; flags management conduct and regulatory issues.",
        tools: "NewsAPI, ChromaDB RAG",
        output: "SentimentAnalysis (−1 to +1)",
        accent: "#60A5FA",
      },
      {
        seat: 4,
        name: "Macro Economist",
        mandate: "RBI rate environment, inflation, GDP growth, and sector tailwinds for India.",
        tools: "RBI scraper, macro DB",
        output: "MacroAnalysis",
        accent: "#60A5FA",
      },
    ],
  },
  {
    id: "debate",
    roundLabel: "Round 2",
    title: "Debate & challenge",
    description: "Each agent reads every other agent's output before writing its own.",
    agents: [
      {
        seat: 5,
        name: "Risk Officer",
        mandate: "Governance failures, fraud indicators, regulatory and concentration risk.",
        tools: "All prior agent outputs",
        output: "RiskAnalysis (score, flags)",
        accent: "#F87171",
      },
      {
        seat: 6,
        name: "Contrarian Investor",
        mandate:
          "Its only job is to disagree: finds flaws in every bull thesis, challenges assumptions.",
        tools: "Full debate state",
        output: "ContrarianReport (counter-arguments)",
        accent: "#F87171",
      },
      {
        seat: 7,
        name: "Valuation Agent",
        mandate: "Runs a DCF model; compares PE/PB/EV-EBITDA against sector peers.",
        tools: "Screener.in, yFinance",
        output: "ValuationOutput (intrinsic value)",
        accent: "#F87171",
      },
    ],
  },
  {
    id: "decision",
    roundLabel: "Round 3",
    title: "Final call",
    description: "No single agent has unchecked authority — the Portfolio Manager reads it all.",
    agents: [
      {
        seat: 8,
        name: "Portfolio Manager",
        mandate: "Weighs the full debate and writes the Investment Memo.",
        tools: "Full pipeline state",
        output: "InvestmentDecision (BUY/HOLD/SELL, memo)",
        accent: "#34D399",
      },
    ],
  },
];

const GRID_COLS: Record<string, string> = {
  research: "lg:grid-cols-4",
  debate: "lg:grid-cols-3",
  decision: "sm:max-w-sm lg:grid-cols-1",
};

function AgentCard({ agent }: { agent: CommitteeAgent }): JSX.Element {
  return (
    <Card
      noPadding
      className="flex h-full flex-col overflow-hidden border-transparent border-t-4 p-5"
      style={{ borderTopColor: agent.accent }}
    >
      <p className="font-mono text-xs text-muted">Seat {agent.seat}</p>
      <h3 className="mt-1 text-sm font-semibold text-ink">{agent.name}</h3>
      <p className="mt-2 flex-1 text-sm leading-relaxed text-muted">{agent.mandate}</p>
      <dl className="mt-4 space-y-1 border-t border-line pt-3 text-xs">
        <div className="flex gap-2">
          <dt className="shrink-0 font-medium text-ink">Tools</dt>
          <dd className="text-muted">{agent.tools}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="shrink-0 font-medium text-ink">Output</dt>
          <dd className="font-mono text-muted">{agent.output}</dd>
        </div>
      </dl>
    </Card>
  );
}

/** A short vertical line + arrow between two rounds -- makes the execution order visible as a flow. */
function RoundConnector(): JSX.Element {
  return (
    <div aria-hidden="true" className="flex justify-center">
      <svg width="20" height="28" viewBox="0 0 20 28" className="text-brand-400/60">
        <line x1="10" y1="0" x2="10" y2="18" stroke="currentColor" strokeWidth="2" />
        <path
          d="M3 15 L10 24 L17 15"
          stroke="currentColor"
          strokeWidth="2"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

/** The 8-agent committee diagram: three execution rounds, colour-coded to match the architecture doc. */
export function CommitteeSection(): JSX.Element {
  return (
    <section id="committee" className="py-16">
      <div className="max-w-2xl">
        <h2 className="font-display text-3xl font-semibold text-ink">
          Eight specialists, one shared state, zero unchecked authority.
        </h2>
        <p className="mt-4 text-base leading-relaxed text-muted">
          Every agent reads and writes to a single LangGraph state object, so the Contrarian and the
          Portfolio Manager always argue from the complete analytical picture — not a summary of it.
        </p>
      </div>

      <div className="mt-10 flex flex-col gap-6">
        {ROUNDS.map((round, index) => (
          <Fragment key={round.id}>
            <div>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-ink">
                  <Badge tone="brand" className="mr-2 align-middle">
                    {round.roundLabel}
                  </Badge>{" "}
                  {round.title}
                </h3>
                <p className="text-sm text-muted">{round.description}</p>
              </div>
              <div
                className={cn("mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2", GRID_COLS[round.id])}
              >
                {round.agents.map((agent) => (
                  <Reveal key={agent.seat} index={agent.seat - 1}>
                    <TiltCard className="h-full">
                      <AgentCard agent={agent} />
                    </TiltCard>
                  </Reveal>
                ))}
              </div>
            </div>
            {index < ROUNDS.length - 1 ? <RoundConnector /> : null}
          </Fragment>
        ))}
      </div>
    </section>
  );
}
