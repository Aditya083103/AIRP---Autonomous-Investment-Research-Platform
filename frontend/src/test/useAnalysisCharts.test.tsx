// frontend/src/test/useAnalysisCharts.test.tsx
// Tests for useAnalysisCharts (T-062). Same renderHook +
// QueryClientProvider wrapper approach as useAnalysisResult.test.tsx --
// global.fetch is mocked so no real network call is made.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAnalysisCharts } from "@/hooks/useAnalysisCharts";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const CHART_DATA_RESPONSE = {
  job_id: "11111111-1111-1111-1111-111111111111",
  ticker: "INFY.NS",
  company_name: "Infosys",
  price_currency: "INR",
  price_history: [{ date: "2026-06-18", close: 1780.5, volume: 1_000_000 }],
  financials: [{ fiscal_year: "FY 2024", revenue_crores: 153_670.0, net_income_crores: 26_233.0 }],
  valuation: null,
  sentiment: null,
  risk: null,
  data_warnings: [
    "Valuation data was not available for this analysis.",
    "Sentiment data was not available for this analysis.",
    "Risk data was not available for this analysis.",
  ],
};

function wrapper({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useAnalysisCharts", () => {
  it("does not fetch when enabled is false", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(
      () => useAnalysisCharts({ jobId: "job-1", accessToken: "jwt-token", enabled: false }),
      { wrapper },
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not fetch when accessToken is null, even if enabled is true", () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useAnalysisCharts({ jobId: "job-1", accessToken: null, enabled: true }), {
      wrapper,
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches and resolves with the AnalysisChartDataResponse once enabled", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAnalysisCharts({ jobId: "job-1", accessToken: "jwt-token", enabled: true }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.data).toEqual(CHART_DATA_RESPONSE));
  });

  it("resolves successfully even when every chart source is null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, CHART_DATA_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAnalysisCharts({ jobId: "job-1", accessToken: "jwt-token", enabled: true }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.valuation).toBeNull();
    expect(result.current.data?.data_warnings).toHaveLength(3);
  });

  it("surfaces a 409 (not ready) response as an error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { detail: "Analysis is not ready yet" }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => useAnalysisCharts({ jobId: "job-1", accessToken: "jwt-token", enabled: true }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
