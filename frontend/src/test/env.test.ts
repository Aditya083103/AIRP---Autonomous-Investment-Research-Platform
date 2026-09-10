// frontend/src/test/env.test.ts
// Tests for src/config/env.ts's WebSocket base URL derivation (T-074 audit
// finding C1/F1). deriveWsBaseUrlFromApiBaseUrl is exported specifically so
// this fallback chain -- explicit VITE_WS_BASE_URL, else derived from an
// absolute VITE_API_BASE_URL, else undefined (window.location fallback in
// the consuming hooks) -- can be tested directly, without the brittleness of
// stubbing import.meta.env across module re-imports.
//
// TestResolveWebSocketBaseUrl (Section C, unit 9 audit finding) covers
// resolveWebSocketBaseUrl -- the shared helper both useAnalysisStream.ts
// and useChatStream.ts now call instead of each keeping its own private
// copy, after useAnalysisStream.ts was found to have silently missed the
// B9 fix (the loud production console.error) that useChatStream.ts
// already had. isProduction/wsBaseUrl are taken as explicit parameters
// specifically so this production-warning branch is testable the same
// way, without stubbing import.meta.env.

import { describe, expect, it, vi } from "vitest";

import { deriveWsBaseUrlFromApiBaseUrl, resolveWebSocketBaseUrl } from "@/config/env";

describe("deriveWsBaseUrlFromApiBaseUrl", () => {
  it("derives wss:// from an absolute https:// API base URL", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("https://airp-api.onrender.com/api/v1")).toBe(
      "wss://airp-api.onrender.com",
    );
  });

  it("derives ws:// from an absolute http:// API base URL", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("http://localhost:8000/api/v1")).toBe(
      "ws://localhost:8000",
    );
  });

  it("preserves a non-default port", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("https://api.example.com:8443/api/v1")).toBe(
      "wss://api.example.com:8443",
    );
  });

  it("returns undefined for the relative local-dev default", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("/api/v1")).toBeUndefined();
  });

  it("returns undefined when apiBaseUrl is undefined", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl(undefined)).toBeUndefined();
  });

  it("returns undefined for a malformed URL rather than throwing", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("https://")).toBeUndefined();
  });

  it("drops any path segment from the API base URL", () => {
    expect(deriveWsBaseUrlFromApiBaseUrl("https://airp-api.onrender.com/api/v1/deep/path")).toBe(
      "wss://airp-api.onrender.com",
    );
  });
});

describe("resolveWebSocketBaseUrl", () => {
  it("returns the explicit wsBaseUrl as-is when provided, in development", () => {
    const url = resolveWebSocketBaseUrl({
      wsBaseUrl: "wss://airp-api.onrender.com",
      isProduction: false,
      callerLabel: "Live analysis progress",
    });
    expect(url).toBe("wss://airp-api.onrender.com");
  });

  it("returns the explicit wsBaseUrl as-is when provided, in production", () => {
    const url = resolveWebSocketBaseUrl({
      wsBaseUrl: "wss://airp-api.onrender.com",
      isProduction: true,
      callerLabel: "Live analysis progress",
    });
    expect(url).toBe("wss://airp-api.onrender.com");
  });

  it("does not warn when wsBaseUrl is provided, even in production", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    resolveWebSocketBaseUrl({
      wsBaseUrl: "wss://airp-api.onrender.com",
      isProduction: true,
      callerLabel: "Live analysis progress",
    });
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("falls back to a window.location-derived URL when wsBaseUrl is undefined", () => {
    const url = resolveWebSocketBaseUrl({
      wsBaseUrl: undefined,
      isProduction: false,
      callerLabel: "Live analysis progress",
    });
    expect(url).toBe(`ws://${window.location.host}`);
  });

  it("does not warn in development when falling back to window.location", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    resolveWebSocketBaseUrl({
      wsBaseUrl: undefined,
      isProduction: false,
      callerLabel: "Live analysis progress",
    });
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it("warns loudly in production when falling back to window.location (B9 regression guard)", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const url = resolveWebSocketBaseUrl({
      wsBaseUrl: undefined,
      isProduction: true,
      callerLabel: "Live analysis progress",
    });

    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy.mock.calls[0]?.[0]).toContain("Live analysis progress");
    expect(errorSpy.mock.calls[0]?.[0]).toContain("VITE_WS_BASE_URL");
    // Still returns a usable (if wrong) URL rather than throwing --
    // the warning is a diagnostic, not a hard failure.
    expect(url).toBe(`ws://${window.location.host}`);
    errorSpy.mockRestore();
  });

  it("includes the caller-specific label in the production warning", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    resolveWebSocketBaseUrl({
      wsBaseUrl: undefined,
      isProduction: true,
      callerLabel: "AIRP Assistant",
    });
    expect(errorSpy.mock.calls[0]?.[0]).toContain("AIRP Assistant");
    errorSpy.mockRestore();
  });
});
