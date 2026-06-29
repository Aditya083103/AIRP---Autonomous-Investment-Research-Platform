// frontend/src/components/layout/RootLayout.tsx
// The persistent app shell: a slim top bar and a footer that wrap every
// routed page via <Outlet />. This is intentionally minimal for T-053 --
// the navigation, auth menu, and responsive behaviour land in their own
// Phase 6 tasks; this only establishes the structural frame and proves the
// nested-route layout pattern works end to end.

import { Link, Outlet } from "react-router-dom";

export function RootLayout(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6">
          <Link to="/" className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold tracking-tight text-brand-600">
              AIRP
            </span>
            <span className="hidden text-sm text-muted sm:inline">
              Autonomous Investment Research Platform
            </span>
          </Link>
          <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
            Phase 6 - Frontend
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-12">
        <Outlet />
      </main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto w-full max-w-6xl px-6 py-6 text-xs text-muted">
          Built as a portfolio project - 8-agent investment committee - FastAPI - LangGraph - React
        </div>
      </footer>
    </div>
  );
}
