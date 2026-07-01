// frontend/src/components/landing/CommitteeSection.tsx
// Landing page (T-055) — the "8 agents diagram" acceptance criterion.
// Deliberately mirrors docs/AIRP_Architecture.drawio rather than inventing
// a fresh visual language: research agents keep the diagram's #1D4ED8,
// the debate/challenge agents keep #B91C1C, and the Portfolio Manager
// keeps #065F46. Grouping into three rounds (parallel research -> debate
// -> final call) reflects the actual LangGraph execution order, not an
// arbitrary layout choice.

import { Card } from "@/components/ui";
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
  readonly title: string;
  readonly description: string;
  readonly agents: readonly CommitteeAgent[];
}

const ROUNDS: readonly CommitteeRound[] = [
  {
    id: "research",
    title: "Round 1 — Parallel research",
    description: "Four analysts gather evidence at the same time; none sees the others yet.",
    agents: [
      {
        seat: 1,
        name: "Fundamental Analyst",
        mandate:
          "Revenue growth, profit margins, free cash flow, debt, and balance-sheet health over 4 years.",
        tools: "yFinance, Alpha Vantage",
        output: "FundamentalAnalysis (score 1–10)",
        accent: "#1D4ED8",
      },
      {
        seat: 2,
        name: "Technical Analyst",
        mandate: "Price trend, 50d/200d moving averages, RSI, momentum, and 52-week positioning.",
        tools: "yFinance OHLCV",
        output: "TechnicalAnalysis (BUY/HOLD/SELL)",
        accent: "#1D4ED8",
      },
      {
        seat: 3,
        name: "News Sentiment Agent",
        mandate: "Scores the last 30 days of news; flags management conduct and regulatory issues.",
        tools: "NewsAPI, ChromaDB RAG",
        output: "SentimentAnalysis (−1 to +1)",
        accent: "#1D4ED8",
      },
      {
        seat: 4,
        name: "Macro Economist",
        mandate: "RBI rate environment, inflation, GDP growth, and sector tailwinds for India.",
        tools: "RBI scraper, macro DB",
        output: "MacroAnalysis",
        accent: "#1D4ED8",
      },
    ],
  },
  {
    id: "debate",
    title: "Round 2 — Debate & challenge",
    description: "Each agent reads every other agent's output before writing its own.",
    agents: [
      {
        seat: 5,
        name: "Risk Officer",
        mandate: "Governance failures, fraud indicators, regulatory and concentration risk.",
        tools: "All prior agent outputs",
        output: "RiskAnalysis (score, flags)",
        accent: "#B91C1C",
      },
      {
        seat: 6,
        name: "Contrarian Investor",
        mandate:
          "Its only job is to disagree: finds flaws in every bull thesis, challenges assumptions.",
        tools: "Full debate state",
        output: "ContrarianReport (counter-arguments)",
        accent: "#B91C1C",
      },
      {
        seat: 7,
        name: "Valuation Agent",
        mandate: "Runs a DCF model; compares PE/PB/EV-EBITDA against sector peers.",
        tools: "Screener.in, yFinance",
        output: "ValuationOutput (intrinsic value)",
        accent: "#B91C1C",
      },
    ],
  },
  {
    id: "decision",
    title: "Final call",
    description: "No single agent has unchecked authority — the Portfolio Manager reads it all.",
    agents: [
      {
        seat: 8,
        name: "Portfolio Manager",
        mandate: "Weighs the full debate and writes the Investment Memo.",
        tools: "Full pipeline state",
        output: "InvestmentDecision (BUY/HOLD/SELL, memo)",
        accent: "#065F46",
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
      className="flex h-full flex-col overflow-hidden border-t-4 p-5"
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

/** The 8-agent committee diagram: three execution rounds, colour-coded to match the architecture doc. */
export function CommitteeSection(): JSX.Element {
  return (
    <section id="committee" className="py-16">
      <div className="max-w-2xl">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">The committee</p>
        <h2 className="mt-3 font-display text-3xl font-semibold text-ink">
          Eight specialists, one shared state, zero unchecked authority.
        </h2>
        <p className="mt-4 text-base leading-relaxed text-muted">
          Every agent reads and writes to a single LangGraph state object, so the Contrarian and the
          Portfolio Manager always argue from the complete analytical picture — not a summary of it.
        </p>
      </div>

      <div className="mt-10 space-y-10">
        {ROUNDS.map((round) => (
          <div key={round.id}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-mono text-sm font-semibold uppercase tracking-wide text-ink">
                {round.title}
              </h3>
              <p className="text-sm text-muted">{round.description}</p>
            </div>
            <div className={cn("mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2", GRID_COLS[round.id])}>
              {round.agents.map((agent) => (
                <AgentCard key={agent.seat} agent={agent} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
