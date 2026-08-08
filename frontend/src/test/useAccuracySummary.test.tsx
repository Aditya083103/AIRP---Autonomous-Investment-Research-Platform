// frontend/src/test/useAccuracySummary.test.tsx
// Tests for useAccuracySummary (T-092). Same renderHook +
// QueryClientProvider wrapper approach as useAnalysisCharts.test.tsx --
// global.fetch is mocked so no real network call is made. Unlike every
// other hook test in this codebase, there is no `enabled`/accessToken
// gating to test here -- useAccuracySummary always fires, since the
// endpoint it wraps is public (see src/api/accuracy.ts's docstring).

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAccuracySummary } from "@/hooks/useAccuracySummary";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAccuracySummary", () => {
  it("fetches immediately with no accessToken or enabled flag required", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, SUMMARY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAccuracySummary(), { wrapper });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("resolves with the AccuracySummaryResponse on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, SUMMARY_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAccuracySummary(), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(SUMMARY_RESPONSE));
  });

  it("surfaces a 500 response as an error", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, { detail: "boom" }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useAccuracySummary(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
