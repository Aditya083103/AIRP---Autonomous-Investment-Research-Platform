// frontend/src/pages/HomePage.tsx
// Home index route. For T-053 this is a foundation page that confirms the
// stack is wired (Vite + React 18 + TS + Tailwind tokens + Router + Query)
// and frames the product. The marketing landing page proper is a later
// Phase 6 task; this stays small but on-brand so the running app already
// reads as AIRP rather than a blank Vite template.

const VERDICTS = [
  { label: "BUY", className: "bg-verdict-buy" },
  { label: "HOLD", className: "bg-verdict-hold" },
  { label: "SELL", className: "bg-verdict-sell" },
] as const;

export function HomePage(): JSX.Element {
  return (
    <div className="mx-auto max-w-3xl">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">
        Investment committee, simulated
      </p>

      <h1 className="mt-4 font-display text-4xl font-semibold leading-tight text-ink sm:text-5xl">
        Eight agents research, debate, and decide - then hand you the memo.
      </h1>

      <p className="mt-6 max-w-memo text-lg leading-relaxed text-muted">
        AIRP runs a structured analysis across specialist agents who challenge each other before
        reaching a verdict on Indian equities, ending in a downloadable Investment Memo with a
        conviction score and price target.
      </p>

      <div className="mt-10 flex flex-wrap items-center gap-3">
        {VERDICTS.map((verdict) => (
          <span
            key={verdict.label}
            className={`rounded-full px-4 py-1.5 font-mono text-sm font-semibold text-white ${verdict.className}`}
          >
            {verdict.label}
          </span>
        ))}
      </div>

      <div className="mt-12 rounded-card border border-line bg-surface p-6 shadow-card">
        <h2 className="text-sm font-semibold text-ink">Frontend foundation ready</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          The Vite + React 18 + TypeScript app is live with Tailwind design tokens, React Router,
          and a shared React Query client. Phase 6 builds the dashboard, live agent progress, debate
          viewer, and memo pages on top of this.
        </p>
      </div>
    </div>
  );
}
