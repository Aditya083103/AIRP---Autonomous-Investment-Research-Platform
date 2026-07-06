// frontend/src/components/error/ErrorBoundary.tsx
// AIRP -- Error boundary (T-066)
//
// React only supports catching render-phase errors via a class
// component's static getDerivedStateFromError/componentDidCatch --
// there is no hook equivalent as of React 18 -- so this is the one
// class component in an otherwise all-function-component codebase,
// same exception every React app with an error boundary makes.
// No `react-error-boundary` package is a project dependency, so this
// hand-rolls that library's two most load-bearing ideas rather than
// inventing something bespoke: a `resetKeys` array (any element
// changing between renders clears the error automatically) and an
// explicit `resetErrorBoundary` escape hatch the fallback UI can call
// directly (the "Try again" button below) -- the same two recovery
// paths that library exposes, hand-rolled for the same "no npm install
// against an unreachable registry" reason CompanyAutocomplete.tsx and
// Tooltip.tsx already document for their own hand-rolled UI.
//
// Mounted once, at the top of App.tsx, wrapping <AppRoutes /> --
// RootErrorBoundary below supplies `resetKeys={[location.pathname]}`
// so navigating to a different route (via the fallback's "Go home"
// link, browser back, or anything else) automatically clears a
// previous page's crash instead of leaving the fallback UI stuck on
// screen forever after the user has moved on.
//
// This is a *last-resort* safety net, not a substitute for the
// specific loading/error/empty states this task also adds to
// DashboardPage, AnalysisResultPage, MemoPage, and ComparePage --
// those handle the expected failure modes (a failed fetch, an
// analysis that didn't complete) with contextual UI in place; this
// boundary exists for the *unexpected* case -- a genuine bug in a
// render path -- where the alternative is React unmounting the whole
// tree and the user seeing a blank white page.

import { Component, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { Button } from "@/components/ui";

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Any element changing (compared with Object.is) between renders clears the error. */
  resetKeys?: readonly unknown[];
}

interface ErrorBoundaryState {
  error: Error | null;
}

function resetKeysChanged(
  previous: readonly unknown[] | undefined,
  next: readonly unknown[] | undefined,
): boolean {
  if (previous === next) {
    return false;
  }
  if (previous === undefined || next === undefined || previous.length !== next.length) {
    return true;
  }
  return previous.some((value, index) => !Object.is(value, next[index]));
}

/** Catches render-phase errors in its subtree; shows a recoverable fallback, not a blank screen. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // A real deployment would forward this to an error-tracking
    // service; console.error is the honest equivalent available here
    // (no such service is configured for this portfolio project), and
    // is explicitly allowed by .eslintrc.cjs's no-console rule.
    console.error("AIRP: unhandled render error", error, info.componentStack);
  }

  componentDidUpdate(previousProps: ErrorBoundaryProps): void {
    const hasError = this.state.error !== null;
    if (hasError && resetKeysChanged(previousProps.resetKeys, this.props.resetKeys)) {
      this.reset();
    }
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }

    return (
      <div className="mx-auto max-w-lg py-16 text-center" role="alert" data-testid="error-boundary">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-verdict-sell">
          Something went wrong
        </p>
        <h1 className="mt-3 font-display text-2xl font-semibold text-ink">
          This page hit an unexpected error.
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          {error.message || "An unexpected error occurred."}
        </p>
        <div className="mt-6 flex items-center justify-center gap-4">
          <Button type="button" variant="secondary" onClick={this.reset}>
            Try again
          </Button>
          {/* A plain <a>, not react-router's <Link>, deliberately -- a full page
              reload guarantees a genuinely clean app state after a render
              crash, rather than a client-side navigation re-using whatever
              state elsewhere in the tree contributed to the crash. */}
          <a href="/" className="text-sm font-medium text-brand-600 hover:text-brand-700">
            Go home
          </a>
        </div>
      </div>
    );
  }
}

/** ErrorBoundary pre-wired to reset on route change. Mount once, at the top of App.tsx. */
export function RootErrorBoundary({ children }: { children: ReactNode }): JSX.Element {
  const location = useLocation();
  return <ErrorBoundary resetKeys={[location.pathname]}>{children}</ErrorBoundary>;
}
