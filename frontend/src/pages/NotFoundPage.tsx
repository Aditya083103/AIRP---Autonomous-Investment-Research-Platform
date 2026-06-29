// frontend/src/pages/NotFoundPage.tsx
// Catch-all 404 route. Plain, directive copy (per the design guidance:
// an empty/error screen is an invitation to act, not a mood piece).

import { Link } from "react-router-dom";

export function NotFoundPage(): JSX.Element {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="font-mono text-sm font-semibold text-brand-600">404</p>
      <h1 className="mt-3 font-display text-3xl font-semibold text-ink">Page not found</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        That page does not exist. Head back to the dashboard to start a new analysis.
      </p>
      <Link
        to="/"
        className="mt-8 inline-block rounded-card bg-brand-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700"
      >
        Back to home
      </Link>
    </div>
  );
}
