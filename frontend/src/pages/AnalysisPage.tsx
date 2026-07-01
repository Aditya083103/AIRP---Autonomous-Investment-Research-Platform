// frontend/src/pages/AnalysisPage.tsx
// Placeholder for the Analysis Input page. T-055's landing page CTAs
// ("Run a live analysis" / "Start a free analysis") link to /analysis so
// there is no dead link on the landing page, but the real form -- company
// autocomplete, PDF upload, validation -- is T-058 (per the master task
// list) and is explicitly out of scope here. This stays a small, honest
// placeholder rather than a fake form, and is not linked from the header
// nav or footer as a "finished" feature.

import { Link } from "react-router-dom";

export function AnalysisPage(): JSX.Element {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-brand-600">Coming soon</p>
      <h1 className="mt-4 font-display text-3xl font-semibold text-ink">
        The analysis input page is being built.
      </h1>
      <p className="mt-4 text-sm leading-relaxed text-muted">
        Company search, PDF upload, and the live 8-agent progress viewer land here in T-058 and
        T-059 of the AIRP build. In the meantime, you can read how the committee works below.
      </p>
      <Link
        to="/#how-it-works"
        className="mt-8 inline-flex h-11 items-center justify-center rounded-card bg-brand-600 px-5 text-sm font-medium text-white transition-colors hover:bg-brand-700"
      >
        See how it works
      </Link>
    </div>
  );
}
