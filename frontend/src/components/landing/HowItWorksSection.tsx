// frontend/src/components/landing/HowItWorksSection.tsx
// Landing page (T-055) — the "how-it-works steps" acceptance criterion.
// Numbered 01-05 deliberately: unlike the committee section (which is
// grouped by execution round, not sequence), this content genuinely is an
// ordered pipeline -- see AIRP_Project_Overview_Updated.docx section 4.2,
// "Request Flow" -- so a numbered list encodes real information here.

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
      "The Risk Officer raises governance flags and the Contrarian Investor challenges every bull case, twice.",
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
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">How it works</p>
        <h2 className="mt-3 font-display text-3xl font-semibold text-ink">
          One request, five stages, no shortcuts.
        </h2>
      </div>

      <ol className="mt-10 space-y-8 border-l border-line pl-8">
        {STEPS.map((step) => (
          <li key={step.number} className="relative">
            <span
              aria-hidden="true"
              className="absolute -left-[34px] top-1 h-2.5 w-2.5 rounded-full bg-brand-600 ring-4 ring-canvas"
            />
            <p className="font-mono text-xs font-semibold text-brand-600">{step.number}</p>
            <h3 className="mt-1 text-lg font-semibold text-ink">{step.title}</h3>
            <p className="mt-1.5 max-w-memo text-sm leading-relaxed text-muted">
              {step.description}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
