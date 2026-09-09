// frontend/src/test/useWebglSupported.test.ts
// Tests for src/hooks/useWebglSupported.ts (B10). jsdom's canvas has no
// WebGL backend, so getContext("webgl"/"webgl2") always returns null
// there -- this hook is expected to report `false` in this test
// environment without any mocking, which is exactly the "keeps
// three.js out of every component test for free" behaviour its
// docstring describes. The true-path (a real WebGL context) is not
// exercised here since jsdom cannot produce one; HeroScene.tsx's own
// tests cover the resulting fallback-rendering behaviour instead.

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useWebglSupported } from "@/hooks/useWebglSupported";

describe("useWebglSupported", () => {
  it("reports false in jsdom, which has no WebGL backend", async () => {
    const { result } = renderHook(() => useWebglSupported());

    await waitFor(() => expect(result.current).toBe(false));
  });
});
