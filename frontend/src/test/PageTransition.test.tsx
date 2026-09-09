// frontend/src/test/PageTransition.test.tsx
// Tests for src/components/motion/PageTransition.tsx (B10). Rendered as
// a layout route (mirrors how RootLayout.tsx actually mounts it) so
// <Outlet /> has a real child route to render.

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PageTransition } from "@/components/motion/PageTransition";

function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

function renderAtRoute(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<PageTransition />}>
          <Route path="/one" element={<p>Page one</p>} />
          <Route path="/two" element={<p>Page two</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PageTransition", () => {
  it("renders the matched route's content", () => {
    stubMatchMedia(false);
    renderAtRoute("/one");
    expect(screen.getByText("Page one")).toBeInTheDocument();
  });

  it("renders the matched route's content under prefers-reduced-motion (bare Outlet)", () => {
    stubMatchMedia(true);
    renderAtRoute("/two");
    expect(screen.getByText("Page two")).toBeInTheDocument();
  });
});
