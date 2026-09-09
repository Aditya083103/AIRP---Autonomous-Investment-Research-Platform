// frontend/src/test/AnimatedNumber.test.tsx
// Tests for src/components/motion/AnimatedNumber.tsx (B10).

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnimatedNumber } from "@/components/motion/AnimatedNumber";

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AnimatedNumber", () => {
  it("renders the final formatted value immediately under prefers-reduced-motion", () => {
    stubMatchMedia(true);
    render(<AnimatedNumber value={1234} />);
    expect(screen.getByText("1,234")).toBeInTheDocument();
  });

  it("eventually renders the final formatted value when animating", async () => {
    stubMatchMedia(false);
    render(<AnimatedNumber value={70} />);
    await waitFor(() => expect(screen.getByText("70")).toBeInTheDocument());
  });

  it("uses a custom format function", () => {
    stubMatchMedia(true);
    render(<AnimatedNumber value={70} format={(value) => `${value.toFixed(1)}%`} />);
    expect(screen.getByText("70.0%")).toBeInTheDocument();
  });
});
