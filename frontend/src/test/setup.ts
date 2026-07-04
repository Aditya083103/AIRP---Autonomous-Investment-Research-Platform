// frontend/src/test/setup.ts
// Vitest setup file (T-054), loaded once before the test suite runs
// (see vitest.config.ts `setupFiles`). Responsibilities: (1) extend
// Vitest's `expect` with jest-dom's DOM matchers (toBeInTheDocument,
// toHaveAttribute, ...) via the side-effecting import, (2) unmount
// every rendered component after each test so one test's DOM doesn't
// leak into the next, and (3)/(4) stub `ResizeObserver` and mock
// `getBoundingClientRect` (T-062) -- jsdom does not implement the
// former and always returns a 0x0 rect for the latter, but Recharts'
// `ResponsiveContainer` (every chart in src/components/charts/)
// constructs a real ResizeObserver on mount and treats a 0x0 rect as
// "not sized yet" (rendering no chart content at all) -- without both
// of these, any test rendering a chart either throws immediately or
// silently renders an empty container.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom lays out every element at 0x0 -- Recharts' ResponsiveContainer
// treats that as "not sized yet" and renders no chart content at all,
// so every chart test would see an empty container. A fixed, non-zero
// rect lets ResponsiveContainer size its children immediately.
Element.prototype.getBoundingClientRect = (): DOMRect =>
  ({
    width: 600,
    height: 300,
    top: 0,
    left: 0,
    right: 600,
    bottom: 300,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }) as DOMRect;

afterEach(() => {
  cleanup();
});
