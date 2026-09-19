// frontend/src/test/HeroPipelinePreview.test.tsx
// Tests for HeroPipelinePreview (landing-page redesign): renders without
// a live connection, freezes to the fully-done frame under
// prefers-reduced-motion, and otherwise advances through its scripted
// timeline via local timers only (no fetch, no WebSocket).

import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HeroPipelinePreview } from "@/components/landing/HeroPipelinePreview";

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
  vi.useRealTimers();
});

describe("HeroPipelinePreview", () => {
  it("renders all 8 pipeline node chips", () => {
    stubMatchMedia(false);
    render(<HeroPipelinePreview />);
    expect(screen.getByTestId("hero-pipeline-preview")).toBeInTheDocument();
    for (const id of [
      "fundamental",
      "technical",
      "sentiment",
      "macro",
      "contrarian",
      "risk",
      "valuation",
      "pm",
    ]) {
      expect(screen.getByTestId(`hero-pipeline-node-${id}`)).toBeInTheDocument();
    }
  });

  it("is hidden from assistive technology (purely illustrative)", () => {
    stubMatchMedia(false);
    render(<HeroPipelinePreview />);
    expect(screen.getByTestId("hero-pipeline-preview")).toHaveAttribute("aria-hidden", "true");
  });

  it("freezes on the fully-done frame under prefers-reduced-motion", () => {
    stubMatchMedia(true);
    render(<HeroPipelinePreview />);
    expect(screen.getByTestId("hero-pipeline-node-fundamental")).toHaveAttribute(
      "data-node-status",
      "done",
    );
    expect(screen.getByTestId("hero-pipeline-node-pm")).toHaveAttribute("data-node-status", "done");
  });

  it("advances research nodes from pending to running via its local timer", () => {
    stubMatchMedia(false);
    vi.useFakeTimers();
    render(<HeroPipelinePreview />);

    expect(screen.getByTestId("hero-pipeline-node-fundamental")).toHaveAttribute(
      "data-node-status",
      "pending",
    );

    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(screen.getByTestId("hero-pipeline-node-fundamental")).toHaveAttribute(
      "data-node-status",
      "running",
    );
  });

  it("makes no network requests", () => {
    stubMatchMedia(false);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<HeroPipelinePreview />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
