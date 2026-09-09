// frontend/src/test/TiltCard.test.tsx
// Tests for src/components/three/TiltCard.tsx (B10). Pointer-driven
// spring physics are not asserted here (that's framer-motion's own
// tested behaviour) -- these tests cover the two things this codebase
// controls: children/className render through, and the reduced-motion
// escape hatch renders a plain wrapper with no tilt machinery attached.

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TiltCard } from "@/components/three/TiltCard";

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

describe("TiltCard", () => {
  it("renders its children", () => {
    stubMatchMedia(false);
    render(
      <TiltCard>
        <p>Card content</p>
      </TiltCard>,
    );
    expect(screen.getByText("Card content")).toBeInTheDocument();
  });

  it("renders the tilt wrapper when motion is allowed", () => {
    stubMatchMedia(false);
    render(
      <TiltCard>
        <p>Card content</p>
      </TiltCard>,
    );
    expect(screen.getByTestId("tilt-card")).toBeInTheDocument();
  });

  it("renders a plain wrapper with no tilt element under prefers-reduced-motion", () => {
    stubMatchMedia(true);
    render(
      <TiltCard>
        <p>Card content</p>
      </TiltCard>,
    );
    expect(screen.getByText("Card content")).toBeInTheDocument();
    expect(screen.queryByTestId("tilt-card")).not.toBeInTheDocument();
  });

  it("passes className through", () => {
    stubMatchMedia(true);
    const { container } = render(
      <TiltCard className="test-class">
        <p>Card content</p>
      </TiltCard>,
    );
    expect(container.querySelector(".test-class")).toBeInTheDocument();
  });
});
