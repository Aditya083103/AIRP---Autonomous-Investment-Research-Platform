// frontend/src/components/layout/RootLayout.tsx
// The persistent app shell: a slim top bar and a footer that wrap every
// routed page via <Outlet />. Structural frame and nested-route layout
// pattern established in T-053; T-056 makes the header auth-aware (the
// static "Phase 6 - Frontend" badge is replaced with real Log in /
// Log out state) now that /login, /register, and /dashboard are real
// routes instead of placeholders.

import { Link, Outlet, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";

function HeaderAuthArea(): JSX.Element {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async (): Promise<void> => {
    await logout();
    navigate("/", { replace: true });
  };

  if (!isAuthenticated) {
    return (
      <div className="flex items-center gap-4">
        <Link to="/login" className="text-sm font-medium text-ink hover:text-brand-600">
          Log in
        </Link>
        <Link
          to="/register"
          className={
            "rounded-card bg-brand-600 px-4 py-2 text-sm font-medium text-white " +
            "transition-colors hover:bg-brand-700"
          }
        >
          Get started
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4">
      <span className="hidden text-sm text-muted sm:inline">{user?.email}</span>
      <Button variant="secondary" size="sm" onClick={() => void handleLogout()}>
        Log out
      </Button>
    </div>
  );
}

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
          <HeaderAuthArea />
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
