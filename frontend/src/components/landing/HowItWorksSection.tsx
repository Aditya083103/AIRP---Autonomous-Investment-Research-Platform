// frontend/src/components/landing/HowItWorksSection.tsx
// Landing page — the "how-it-works steps" acceptance criterion.
// Numbered 01-05 deliberately: unlike the committee section (which is
// grouped by execution round, not sequence), this content genuinely is an
// ordered pipeline -- see AIRP_Project_Overview_Updated.docx section 4.2,
// "Request Flow" -- so a numbered list encodes real information here.
//
// B10: each step's text is wrapped in Reveal (staggered fade/rise-in by
// step index), matching the cascading-entrance treatment given to every
// other list/grid this unit touches. The timeline dot stays a direct
// child of <li> (not inside the Reveal wrapper) so its `absolute -left`
// positioning keeps resolving against the <li>'s own `relative` -- the
// wrapper only ever contains the text content beside it.

import { Reveal } from "@/components/motion/Reveal";

interface Step {
  readonly number: string;
  readonly title: string;
  readonly description: string;
}

const STEPS: readonly Step[] = [
  {
    number: "01",
    title: "Name a company",
    description:
      "Type a ticker or company name -- or two, to compare -- and optionally attach an annual report or earnings call transcript.",
  },
  {
    number: "02",
    title: "Four analysts research in parallel",
    description:
      "Fundamental, Technical, News Sentiment, and Macro Economist gather data from free market APIs at the same time.",
  },
  {
    number: "03",
    title: "The committee debates",
    description:
      "The Risk Officer raises governance flags and the Contrarian Investor challenges every bull case -- escalating to a second round when its pushback is strong enough to warrant one.",
  },
  {
    number: "04",
    title: "Valuation closes the gap",
    description:
      "The Valuation Agent runs a DCF model and checks the stock against its sector peers on Indian market data.",
  },
  {
    number: "05",
    title: "The Portfolio Manager decides",
    description:
      "A BUY, HOLD, or SELL call with a conviction score and a downloadable Investment Memo -- usually in under 90 seconds.",
  },
];

/** A genuinely sequential 5-step walkthrough of one analysis run. */
export function HowItWorksSection(): JSX.Element {
  return (
    <section id="how-it-works" className="py-16">
      <div className="max-w-2xl">
        <h2 className="font-display text-3xl font-semibold text-ink">
          One request, five stages, no shortcuts.
        </h2>
      </div>

      <ol className="mt-10 space-y-8 border-l border-line pl-8">
        {STEPS.map((step, index) => (
          <li key={step.number} className="relative">
            <span
              aria-hidden="true"
              className="absolute -left-[34px] top-1 h-2.5 w-2.5 rounded-full bg-brand-600 ring-4 ring-canvas"
            />
            <Reveal index={index}>
              <p className="font-mono text-xs font-semibold text-brand-300">{step.number}</p>
              <h3 className="mt-1 text-lg font-semibold text-ink">{step.title}</h3>
              <p className="mt-1.5 max-w-memo text-sm leading-relaxed text-muted">
                {step.description}
              </p>
            </Reveal>
          </li>
        ))}
      </ol>
    </section>
  );
}
