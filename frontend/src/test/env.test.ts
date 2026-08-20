// frontend/src/test/env.test.ts
// Tests for src/config/env.ts's WebSocket base URL derivation (T-074 audit
// finding C1/F1). deriveWsBaseUrlFromApiBaseUrl is exported specifically so
// this fallback chain -- explicit VITE_WS_BASE_URL, else derived from an
// absolute VITE_API_BASE_URL, else undefined (window.location fallback in
// the consuming hooks) -- can be tested directly, without the brittleness of
// stubbing import.meta.env across module re-imports.

import { describe, expect, it } from "vitest";

import { deriveWsBaseUrlFromApiBaseUrl } from "@/config/env";

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
