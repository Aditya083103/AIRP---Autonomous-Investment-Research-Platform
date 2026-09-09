// frontend/src/test/HeroScene.test.tsx
// Tests for src/components/three/HeroScene.tsx (B10). jsdom has no
// WebGL backend (see useWebglSupported.ts's own docstring), so
// useWebglSupported() always resolves to `false` in this test
// environment -- HeroScene therefore always renders StaticHeroFallback
// here, regardless of the reduced-motion stub. That is the correct,
// intentional behaviour this test asserts: three.js/@react-three/fiber
// are never exercised (or even needed) in the test suite at all.

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HeroScene } from "@/components/three/HeroScene";

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

describe("HeroScene", () => {
  it("renders the static fallback when WebGL is unavailable (jsdom has no WebGL backend)", async () => {
    stubMatchMedia(false);
    render(<HeroScene />);
    await waitFor(() => expect(screen.getByTestId("hero-scene-fallback")).toBeInTheDocument());
    expect(screen.queryByTestId("hero-scene-canvas")).not.toBeInTheDocument();
  });

  it("renders the static fallback under prefers-reduced-motion", async () => {
    stubMatchMedia(true);
    render(<HeroScene />);
    await waitFor(() => expect(screen.getByTestId("hero-scene-fallback")).toBeInTheDocument());
  });

  it("is hidden from assistive technology", async () => {
    stubMatchMedia(false);
    render(<HeroScene />);
    const fallback = await screen.findByTestId("hero-scene-fallback");
    expect(fallback).toHaveAttribute("aria-hidden", "true");
  });

  it("passes className through to the fallback", async () => {
    stubMatchMedia(false);
    render(<HeroScene className="test-class" />);
    const fallback = await screen.findByTestId("hero-scene-fallback");
    expect(fallback).toHaveClass("test-class");
  });
});
