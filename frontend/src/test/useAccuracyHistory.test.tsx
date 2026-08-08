// frontend/src/test/useAccuracyHistory.test.tsx
// Tests for useAccuracyHistory (T-092). Same shape as
// useAccuracySummary.test.tsx -- see that file's docstring for why
// there is no enabled/accessToken gating to test.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MAX_ACCURACY_HISTORY_PAGE_SIZE, useAccuracyHistory } from "@/hooks/useAccuracyHistory";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const HISTORY_RESPONSE = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      analysis_id: "22222222-2222-2222-2222-222222222222",
      ticker: "TCS.NS",
      verdict: "BUY",
      conviction_score: 8,
      price_at_verdict: 3000.0,
      verdict_date: "2026-01-01T00:00:00Z",
      evaluation_horizon_days: 90,
      price_at_evaluation: 3200.0,
      price_change_pct: 6.6667,
      directional_correct: true,
      evaluated_at: "2026-04-01T00:00:00Z",
    },
  ],
  total_count: 1,
  limit: 100,
  offset: 0,
  has_more: false,
};

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAccuracyHistory", () => {
  it("fetches immediately with no accessToken or enabled flag required", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAccuracyHistory(), { wrapper });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("defaults to MAX_ACCURACY_HISTORY_PAGE_SIZE and offset 0", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAccuracyHistory(), { wrapper });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`limit=${MAX_ACCURACY_HISTORY_PAGE_SIZE}`);
    expect(url).toContain("offset=0");
  });

  it("forwards an explicit limit/offset", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAccuracyHistory({ limit: 20, offset: 40 }), { wrapper });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("limit=20");
    expect(url).toContain("offset=40");
  });

  it("resolves with the AccuracyHistoryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, HISTORY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAccuracyHistory(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(HISTORY_RESPONSE));
  });

  it("surfaces a 500 response as an error", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAccuracyHistory(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
