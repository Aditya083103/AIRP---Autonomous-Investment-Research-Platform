// frontend/src/test/accuracyApi.test.ts
// Tests for src/api/accuracy.ts (T-092): request shape (URL, query
// params, and -- unlike every other API client in this project -- the
// explicit ABSENCE of an Authorization header, since both endpoints are
// public) and AccuracyApiError message extraction, mirroring
// test/analysisApi.test.ts's approach for the same two FastAPI
// error-body shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import { AccuracyApiError, fetchAccuracyHistory, fetchAccuracySummary } from "@/api/accuracy";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const SUMMARY_RESPONSE = {
  total_evaluated: 10,
  total_pending: 2,
  overall_accuracy_pct: 70.0,
  by_verdict: [
    { verdict: "BUY", evaluated_count: 5, correct_count: 4, accuracy_pct: 80.0 },
    { verdict: "HOLD", evaluated_count: 3, correct_count: 2, accuracy_pct: 66.67 },
    { verdict: "SELL", evaluated_count: 2, correct_count: 1, accuracy_pct: 50.0 },
  ],
  by_conviction: [
    {
      bucket: "low",
      label: "Low (1-3)",
      min_score: 1,
      max_score: 3,
      evaluated_count: 1,
      correct_count: 0,
      accuracy_pct: 0.0,
    },
    {
      bucket: "medium",
      label: "Medium (4-6)",
      min_score: 4,
      max_score: 6,
      evaluated_count: 4,
      correct_count: 3,
      accuracy_pct: 75.0,
    },
    {
      bucket: "high",
      label: "High (7-10)",
      min_score: 7,
      max_score: 10,
      evaluated_count: 5,
      correct_count: 4,
      accuracy_pct: 80.0,
    },
  ],
};

const HISTORY_RESPONSE = {
  items: [],
  total_count: 0,
  limit: 20,
  offset: 0,
  has_more: false,
};

describe("fetchAccuracySummary", () => {
  it("requests GET /accuracy/summary with no Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, SUMMARY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAccuracySummary();

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/accuracy/summary");
    expect(options.method).toBe("GET");
    const headers = (options.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("resolves with the AccuracySummaryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, SUMMARY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAccuracySummary();

    expect(result).toEqual(SUMMARY_RESPONSE);
  });

  it("throws AccuracyApiError with the backend's detail string on failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAccuracySummary()).rejects.toThrow("boom");
  });

  it("throws an AccuracyApiError instance carrying the status code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAccuracySummary().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(AccuracyApiError);
    expect((error as AccuracyApiError).status).toBe(500);
  });
});

describe("fetchAccuracyHistory", () => {
  it("requests /accuracy/history with no auth header, no query params by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAccuracyHistory();

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/accuracy/history");
    expect(url).not.toContain("?");
    const headers = (options.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it("includes limit and offset as query params when given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAccuracyHistory({ limit: 100, offset: 40 });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("limit=100");
    expect(url).toContain("offset=40");
  });

  it("resolves with the AccuracyHistoryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAccuracyHistory({ limit: 20, offset: 0 });

    expect(result).toEqual(HISTORY_RESPONSE);
  });

  it("throws AccuracyApiError with the backend's detail string on failure", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(422, { detail: [{ msg: "limit too large" }] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAccuracyHistory({ limit: 9999 })).rejects.toThrow("limit too large");
  });

  it("throws an AccuracyApiError instance carrying the status code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(422, { detail: "bad request" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAccuracyHistory().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(AccuracyApiError);
    expect((error as AccuracyApiError).status).toBe(422);
  });
});
