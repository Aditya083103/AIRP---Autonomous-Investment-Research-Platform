// frontend/src/test/Reveal.test.tsx
// Tests for src/components/motion/Reveal.tsx (B10).

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Reveal } from "@/components/motion/Reveal";

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

describe("Reveal", () => {
  it("renders its children", () => {
    stubMatchMedia(false);
    render(
      <Reveal>
        <p>Card content</p>
      </Reveal>,
    );
    expect(screen.getByText("Card content")).toBeInTheDocument();
  });

  it("renders a plain unanimated wrapper under prefers-reduced-motion", () => {
    stubMatchMedia(true);
    const { container } = render(
      <Reveal>
        <p>Card content</p>
      </Reveal>,
    );
    expect(screen.getByText("Card content")).toBeInTheDocument();
    // A plain <div>, not a motion.div with style-driven opacity/transform.
    expect(container.querySelector("div")?.getAttribute("style")).toBeNull();
  });

  it("passes className through to the wrapper", () => {
    stubMatchMedia(false);
    const { container } = render(
      <Reveal className="test-class">
        <p>Card content</p>
      </Reveal>,
    );
    expect(container.querySelector(".test-class")).toBeInTheDocument();
  });
});
