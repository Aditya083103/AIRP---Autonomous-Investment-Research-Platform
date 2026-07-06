// frontend/src/components/layout/RootLayout.tsx
// The persistent app shell: a top bar and a footer that wrap every
// routed page via <Outlet />. Structural frame and nested-route layout
// pattern established in T-053; T-056 made the header auth-aware (real
// Log in / Log out state); T-065 adds primary navigation (New analysis,
// Compare, Dashboard) that collapses into a hamburger-triggered panel
// below the `md` (768px) breakpoint -- the same breakpoint every other
// Phase 6 page already treats as "mobile vs desktop" (e.g.
// ChartsPanel.tsx's `md:grid-cols-3`, AuthCard's stacked forms).
//
// Auth actions (Log in/Get started, or the signed-in email + Log out)
// are deliberately NOT duplicated inside the mobile panel -- they stay
// in the header bar itself at every width, since they're already
// compact (the email is hidden below `sm` via T-056's own
// `hidden sm:inline`, leaving just a short "Log out" button). Only the
// three primary nav links collapse -- keeping HeaderAuthArea to a
// single rendered instance is also what keeps RootLayout.test.tsx's
// existing `getByRole("link", { name: "Log in" })`-style single-match
// queries valid unchanged after this task.

import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/cn";

interface PrimaryNavLink {
  readonly to: string;
  readonly label: string;
}

const PRIMARY_NAV_LINKS: readonly PrimaryNavLink[] = [
  { to: "/analysis", label: "New analysis" },
  { to: "/compare", label: "Compare" },
  { to: "/dashboard", label: "Dashboard" },
];

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return cn(
    "text-sm font-medium transition-colors",
    isActive ? "text-brand-600" : "text-muted hover:text-ink",
  );
}

/** The three primary routes, rendered inline for both the desktop bar and the mobile panel. */
interface PrimaryNavProps {
  className?: string;
  onNavigate?: () => void;
}

function PrimaryNav({ className, onNavigate }: PrimaryNavProps): JSX.Element {
  return (
    <nav aria-label="Primary" className={className}>
      {PRIMARY_NAV_LINKS.map((link) => (
        <NavLink key={link.to} to={link.to} className={navLinkClassName} onClick={onNavigate}>
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}

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

function MenuIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M3 5.5h14M3 10h14M3 14.5h14"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CloseIcon(): JSX.Element {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M5 5l10 10M15 5L5 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function RootLayout(): JSX.Element {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();

  // Closes the mobile panel on every route change -- without this, a
  // link tapped inside the panel would navigate but leave the panel
  // rendered open behind the new page.
  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-8">
            <Link to="/" className="flex items-center gap-2">
              <span className="font-mono text-sm font-semibold tracking-tight text-brand-600">
                AIRP
              </span>
              <span className="hidden text-sm text-muted sm:inline">
                Autonomous Investment Research Platform
              </span>
            </Link>

            <PrimaryNav className="hidden items-center gap-6 md:flex" />
          </div>

          <div className="flex items-center gap-4">
            <HeaderAuthArea />

            <button
              type="button"
              aria-label={isMobileMenuOpen ? "Close menu" : "Open menu"}
              aria-expanded={isMobileMenuOpen}
              aria-controls="mobile-nav-panel"
              onClick={() => setIsMobileMenuOpen((open) => !open)}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-card text-ink",
                "transition-colors hover:bg-canvas focus-visible:outline-none",
                "focus-visible:ring-2 focus-visible:ring-brand-500 md:hidden",
              )}
            >
              {isMobileMenuOpen ? <CloseIcon /> : <MenuIcon />}
            </button>
          </div>
        </div>

        {isMobileMenuOpen ? (
          <div
            id="mobile-nav-panel"
            data-testid="mobile-nav-panel"
            className="border-t border-line bg-surface px-6 py-4 md:hidden"
          >
            <PrimaryNav
              className="flex flex-col gap-4"
              onNavigate={() => setIsMobileMenuOpen(false)}
            />
          </div>
        ) : null}
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
