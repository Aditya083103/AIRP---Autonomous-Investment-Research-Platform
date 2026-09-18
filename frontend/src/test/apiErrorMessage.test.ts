// frontend/src/test/apiErrorMessage.test.ts
// Tests for src/lib/apiErrorMessage.ts -- the raw-network-failure
// detector and friendly-message resolver behind the accuracy-page
// "Failed to fetch" bug fix (a Render free-tier cold start rejects
// fetch() with a raw browser TypeError before any HTTP response
// arrives, and that literal message used to reach the UI verbatim).

import { describe, expect, it } from "vitest";

import {
  getDisplayErrorMessage,
  isNetworkError,
  NETWORK_ERROR_MESSAGE,
} from "@/lib/apiErrorMessage";

describe("isNetworkError", () => {
  it.each([
    "Failed to fetch",
    "NetworkError when attempting to fetch resource.",
    "Load failed",
    "Network request failed",
  ])("recognises the browser-native fetch rejection message %j", (message) => {
    expect(isNetworkError(new TypeError(message))).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isNetworkError(new TypeError("FAILED TO FETCH"))).toBe(true);
  });

  it("returns false for a non-network TypeError", () => {
    expect(isNetworkError(new TypeError("Cannot read properties of undefined"))).toBe(false);
  });

  it("returns false for a plain Error (e.g. AccuracyApiError-style errors)", () => {
    expect(isNetworkError(new Error("Something went wrong. Please try again."))).toBe(false);
  });

  it("returns false for a non-Error throw", () => {
    expect(isNetworkError("some string")).toBe(false);
  });
});

describe("getDisplayErrorMessage", () => {
  it("rewrites a raw network failure to the friendly cold-start message", () => {
    expect(getDisplayErrorMessage(new TypeError("Failed to fetch"), "fallback")).toBe(
      NETWORK_ERROR_MESSAGE,
    );
  });

  it("keeps an ordinary Error's own message", () => {
    expect(getDisplayErrorMessage(new Error("Verdict not found"), "fallback")).toBe(
      "Verdict not found",
    );
  });

  it("uses the fallback for a non-Error throw", () => {
    expect(getDisplayErrorMessage("boom", "fallback")).toBe("fallback");
  });

  it("uses the fallback for an Error with an empty message", () => {
    expect(getDisplayErrorMessage(new Error(""), "fallback")).toBe("fallback");
  });
});
