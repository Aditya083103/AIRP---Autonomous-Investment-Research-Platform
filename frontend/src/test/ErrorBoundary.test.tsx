// frontend/src/test/ErrorBoundary.test.tsx
// Tests for ErrorBoundary (T-066). React logs caught errors to the
// console itself (in addition to this component's own
// componentDidCatch) -- every test here spies on console.error and
// restores it in afterEach so those expected logs don't clutter (or
// fail, under a stricter console-assertion setup) the test run.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary, RootErrorBoundary } from "@/components/error/ErrorBoundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }): JSX.Element {
  if (shouldThrow) {
    throw new Error("Boom");
  }
  return <p>Rendered fine</p>;
}

/**
 * Throws for as long as `shouldThrow` is true; the test flips it directly.
 *
 * Deliberately NOT driven by a call counter: React's development-mode
 * error handling invokes a throwing component some number of extra
 * times internally (to get a clean native stack trace) before the
 * nearest boundary's componentDidCatch ever runs, and that count is an
 * unstable implementation detail, not something worth guessing at (two
 * different guesses -- a single boolean flip, then "throw for the
 * first two calls" -- both flipped this bomb into its non-throwing
 * branch before the boundary ever caught anything, failing this test
 * the same way both times). Setting `shouldThrow` externally, and
 * leaving it unconditionally true for the entire first mount attempt
 * however many times React invokes this function during it, is what
 * actually guarantees the boundary catches before the test flips it to
 * false and clicks "Try again".
 */
const thrownOnceState = { shouldThrow: true };

function ThrowsOnceBomb(): JSX.Element {
  if (thrownOnceState.shouldThrow) {
    throw new Error("First render always fails");
  }
  return <p>Recovered</p>;
}

/** Toggles Bomb's shouldThrow prop via a button -- used to test resetKeys-driven recovery. */
function ToggleableBomb(): JSX.Element {
  const [key, setKey] = useState(0);
  return (
    <div>
      <button type="button" onClick={() => setKey((value) => value + 1)}>
        Change key
      </button>
      <ErrorBoundary resetKeys={[key]}>
        <Bomb shouldThrow={key === 0} />
      </ErrorBoundary>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("renders children normally when nothing throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Rendered fine")).toBeInTheDocument();
  });

  it("shows the fallback UI instead of crashing when a child throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();
    expect(screen.getByText("This page hit an unexpected error.")).toBeInTheDocument();
    expect(screen.getByText("Boom")).toBeInTheDocument();
    expect(screen.queryByText("Rendered fine")).not.toBeInTheDocument();
  });

  it("logs the caught error via console.error", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(consoleSpy).toHaveBeenCalledWith(
      "AIRP: unhandled render error",
      expect.any(Error),
      expect.any(String),
    );
  });

  it("recovers when resetKeys changes after an error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    render(<ToggleableBomb />);

    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Change key" }));

    expect(screen.queryByTestId("error-boundary")).not.toBeInTheDocument();
    expect(screen.getByText("Rendered fine")).toBeInTheDocument();
  });

  it("re-attempts rendering the same subtree when Try again is clicked", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    thrownOnceState.shouldThrow = true;
    const user = userEvent.setup();
    render(
      <ErrorBoundary>
        <ThrowsOnceBomb />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();

    // Flipped here, not inside ThrowsOnceBomb itself: the boundary must
    // already have caught the error above before this changes anything,
    // so the only render attempt this flag affects is the one "Try
    // again" triggers below.
    thrownOnceState.shouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.queryByTestId("error-boundary")).not.toBeInTheDocument();
    expect(screen.getByText("Recovered")).toBeInTheDocument();
  });
});

describe("RootErrorBoundary", () => {
  it("resets a caught error after navigating to a different route", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();

    // The nav Link deliberately lives OUTSIDE RootErrorBoundary: a
    // caught error unmounts everything the boundary wraps, so a link
    // that triggers recovery cannot itself be inside the crashed
    // subtree. This mirrors how the fallback's own "Go home" affordance
    // in ErrorBoundary.tsx has to be a plain external link for the same
    // reason -- this test exercises RootErrorBoundary's resetKeys
    // contract in isolation (any external location change recovers it),
    // not App.tsx's specific layout.
    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <nav>
          <Link to="/safe">Go to safe page</Link>
        </nav>
        <RootErrorBoundary>
          <Routes>
            <Route path="/broken" element={<Bomb shouldThrow={true} />} />
            <Route path="/safe" element={<p>Safe page</p>} />
          </Routes>
        </RootErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("error-boundary")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Go to safe page" }));

    expect(screen.queryByTestId("error-boundary")).not.toBeInTheDocument();
    expect(screen.getByText("Safe page")).toBeInTheDocument();
  });
});
