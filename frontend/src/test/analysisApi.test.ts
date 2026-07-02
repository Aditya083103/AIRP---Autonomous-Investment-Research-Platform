// frontend/src/test/analysisApi.test.ts
// Tests for src/api/analysis.ts (T-057): request shape (URL, query
// params, Authorization header) and AnalysisApiError message
// extraction, mirroring test/authApi.test.ts's approach for the same
// two FastAPI error-body shapes.

import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisApiError, fetchAnalysisHistory } from "@/api/analysis";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const HISTORY_RESPONSE = {
  items: [],
  total_count: 0,
  limit: 20,
  offset: 0,
  has_more: false,
};

describe("fetchAnalysisHistory", () => {
  it("sends the Authorization header with the given token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token", limit: 20, offset: 0 });

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-token");
  });

  it("includes limit and offset as query params", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token", limit: 20, offset: 40 });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/analysis/history");
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
  });

  it("omits query params that were not given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalysisHistory({ accessToken: "jwt-token" });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url.endsWith("/analysis/history")).toBe(true);
  });

  it("resolves with the parsed HistoryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalysisHistory({ accessToken: "jwt-token" });

    expect(result).toEqual(HISTORY_RESPONSE);
  });

  it("throws AnalysisApiError with the backend's detail string on failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Not authenticated" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAnalysisHistory({ accessToken: "bad-token" })).rejects.toThrow(
      "Not authenticated",
    );
  });

  it("throws an AnalysisApiError instance carrying the status code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const error = await fetchAnalysisHistory({ accessToken: "jwt-token" }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(AnalysisApiError);
    expect((error as AnalysisApiError).status).toBe(500);
  });
});
