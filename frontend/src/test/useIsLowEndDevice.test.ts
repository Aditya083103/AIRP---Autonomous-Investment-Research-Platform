// frontend/src/test/useIsLowEndDevice.test.ts
// Tests for src/hooks/useIsLowEndDevice.ts (Section C audit finding,
// deferred from unit 9). Exercises the three signals independently by
// stubbing navigator.hardwareConcurrency/deviceMemory directly (jsdom
// lets these be overridden with Object.defineProperty since they are
// plain getters on the real Navigator prototype) and window.matchMedia
// via vi.stubGlobal, the same approach HeroScene.test.tsx already uses.

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useIsLowEndDevice } from "@/hooks/useIsLowEndDevice";

const originalHardwareConcurrency = navigator.hardwareConcurrency;

function stubHardwareConcurrency(value: number | undefined): void {
  Object.defineProperty(navigator, "hardwareConcurrency", {
    value,
    configurable: true,
  });
}

function stubDeviceMemory(value: number | undefined): void {
  Object.defineProperty(navigator, "deviceMemory", {
    value,
    configurable: true,
  });
}

function stubMatchMedia(matchingQueries: string[]): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: matchingQueries.includes(query),
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
  stubHardwareConcurrency(originalHardwareConcurrency);
  stubDeviceMemory(undefined);
  vi.unstubAllGlobals();
});

describe("useIsLowEndDevice", () => {
  it("reports false for a typical desktop (many cores, no deviceMemory signal, no coarse pointer)", async () => {
    stubHardwareConcurrency(16);
    stubMatchMedia([]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("reports true when hardwareConcurrency is at or below the low-end threshold", async () => {
    stubHardwareConcurrency(4);
    stubMatchMedia([]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("reports false when hardwareConcurrency is just above the low-end threshold", async () => {
    stubHardwareConcurrency(6);
    stubMatchMedia([]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("reports true when deviceMemory is at or below the low-end threshold, even with many cores", async () => {
    stubHardwareConcurrency(16);
    stubDeviceMemory(2);
    stubMatchMedia([]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("ignores an absent deviceMemory rather than treating unknown as low-end", async () => {
    stubHardwareConcurrency(16);
    stubDeviceMemory(undefined);
    stubMatchMedia([]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("reports true for a coarse pointer combined with a narrow (phone-width) viewport, even with many cores", async () => {
    stubHardwareConcurrency(16);
    stubMatchMedia(["(pointer: coarse)", "(max-width: 480px)"]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("reports false for a coarse pointer alone without a narrow viewport (e.g. a touchscreen laptop)", async () => {
    stubHardwareConcurrency(16);
    stubMatchMedia(["(pointer: coarse)"]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(false));
  });

  it("reports false for a narrow viewport alone without a coarse pointer (e.g. a resized desktop window)", async () => {
    stubHardwareConcurrency(16);
    stubMatchMedia(["(max-width: 480px)"]);

    const { result } = renderHook(() => useIsLowEndDevice());

    await waitFor(() => expect(result.current).toBe(false));
  });
});
