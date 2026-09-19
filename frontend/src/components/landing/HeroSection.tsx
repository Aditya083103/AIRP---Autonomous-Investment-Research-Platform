// frontend/src/components/landing/HeroSection.tsx
// Landing page — the page's opening thesis. Pairs the product promise
// (eight agents converge on one defensible verdict) with a static
// "example output" card instead of a generic stat block: a condensed
// preview of what the live agent-progress viewer and the final verdict
// actually look like. Labelled "Example output" throughout so it never
// reads as a live or real recommendation.
//
// Landing-page redesign: the old HeroScene (a decorative gradient blob /
// floating 3D shape with no connection to the actual product) is
// replaced by HeroPipelinePreview -- a small, scripted animation of
// AIRP's own research -> debate -> decision pipeline, stacked in-flow
// above the example-output card rather than absolutely positioned
// behind the headline. Being real (if illustrative) content now, not
// decoration, it no longer needs the old component's `pointer-events-none`/
// negative-z-index/`hidden lg:block` treatment -- it simply participates
// in the two-column grid's normal flow and stacks with everything else
// below `lg`.

import { Link } from "react-router-dom";

import { HeroPipelinePreview } from "@/components/landing/HeroPipelinePreview";
import { Reveal } from "@/components/motion/Reveal";
import { TiltCard } from "@/components/three/TiltCard";
import { Badge } from "@/components/ui";

interface ExampleAgentDot {
  readonly label: string;
  readonly status: "done" | "running";
}

const EXAMPLE_AGENTS: readonly ExampleAgentDot[] = [
  { label: "Fundamental", status: "done" },
  { label: "Technical", status: "done" },
  { label: "News sentiment", status: "done" },
  { label: "Macro", status: "done" },
  { label: "Risk officer", status: "done" },
  { label: "Contrarian", status: "done" },
  { label: "Valuation", status: "done" },
  { label: "Portfolio manager", status: "running" },
];

/** The hero: headline, subhead, primary/secondary CTAs, and the example-output card. */
export function HeroSection(): JSX.Element {
  return (
    <section className="py-4 lg:py-12">
      <div className="grid items-center gap-12 lg:grid-cols-[1.1fr,0.9fr]">
        <Reveal>
          <div>
            <h1 className="font-display text-4xl font-semibold leading-tight text-ink sm:text-5xl">
              Eight agents research, debate, and decide — then hand you the memo.
            </h1>

            <p className="mt-6 max-w-memo text-lg leading-relaxed text-muted">
              Name an Indian equity and AIRP runs a structured investment-committee process: four
              analysts research in parallel, a Risk Officer and Contrarian Investor challenge every
              claim, and a Portfolio Manager reads the full debate before committing to a BUY, HOLD,
              or SELL — with a conviction score and a downloadable Investment Memo.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-4">
              <Link
                to="/analysis"
                className="inline-flex h-12 items-center justify-center rounded-card bg-brand-600 px-6 text-base font-medium text-white transition-colors hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
              >
                Run a live analysis
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex h-12 items-center justify-center rounded-card border border-line bg-surface px-6 text-base font-medium text-ink transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
              >
                See how it works
              </a>
            </div>
          </div>
        </Reveal>

        <Reveal index={1}>
          <div className="flex flex-col gap-6">
            <HeroPipelinePreview />

            <TiltCard>
              <div
                aria-label="Example AIRP output"
                className="rounded-card border border-line bg-surface p-6"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-mono text-xs text-muted">Example output</p>
                    <p className="mt-1 font-mono text-sm font-semibold text-ink">INFY.NS</p>
                  </div>
                  <Badge tone="buy">BUY</Badge>
                </div>

                <dl className="mt-4 flex items-baseline gap-2">
                  <dt className="text-xs text-muted">Conviction score</dt>
                  <dd className="font-mono text-sm font-semibold text-ink">8 / 10</dd>
                </dl>

                <ul className="mt-6 grid grid-cols-4 gap-3" aria-label="Committee status">
                  {EXAMPLE_AGENTS.map((agent) => (
                    <li key={agent.label} className="flex flex-col items-center gap-1.5">
                      <span
                        aria-label={`${agent.label}: ${agent.status === "done" ? "complete" : "in progress"}`}
                        className={
                          agent.status === "done"
                            ? "h-2.5 w-2.5 rounded-full bg-verdict-buy"
                            : "h-2.5 w-2.5 animate-pulse rounded-full bg-brand-500"
                        }
                      />
                      <span className="text-center text-[10px] leading-tight text-muted">
                        {agent.label}
                      </span>
                    </li>
                  ))}
                </ul>

                <p className="mt-6 border-t border-line pt-4 text-xs leading-relaxed text-muted">
                  Portfolio Manager is synthesising the debate. A real run finishes in under 90
                  seconds.
                </p>
              </div>
            </TiltCard>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
